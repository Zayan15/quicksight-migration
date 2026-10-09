import boto3
import json
import time
import subprocess
import argparse
import os
import re
import datetime



REGION = 'us-west-2'

def run_aws_cli(cmd_list):
    env = os.environ.copy()
    env['PYTHONUTF8'] = '1'
    result = subprocess.run(cmd_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        stdout_text = result.stdout.decode('utf-8')
    except UnicodeDecodeError:
        stdout_text = result.stdout.decode('utf-8', errors='replace')
    if result.returncode != 0:
        try:
            error_text = result.stderr.decode('utf-8')
        except UnicodeDecodeError:
            error_text = result.stderr.decode('utf-8', errors='replace')
        raise Exception(error_text)
    return json.loads(stdout_text)

def sanitize_id(name):
    return re.sub(r'[^\w\-]', '', name.replace(" ", "-"))


def get_profile_info(profile):
    """Returns (account_id, qs_username) derived from the profile's caller identity."""
    result = run_aws_cli(['aws', 'sts', 'get-caller-identity', '--profile', profile])
    account_id = result['Account']
    # ARN format: arn:aws:sts::account:assumed-role/RoleName/SessionName
    arn = result.get('Arn', '')
    parts = arn.split(':')
    # parts[-1] is 'assumed-role/RoleName/SessionName'
    assumed = parts[-1]  # e.g. assumed-role/AWSReservedSSO_rw_xxx/user@example.com
    role_and_session = '/'.join(assumed.split('/')[1:])  # RoleName/SessionName
    return account_id, role_and_session

def validate_profile(profile):
    try:
        run_aws_cli(['aws', 'sts', 'get-caller-identity', '--profile', profile])
    except Exception as e:
        raise Exception(f"\n AWS profile '{profile}' is not valid or has expired.\nDetails: {str(e)}")

def get_analysis_id_by_name(profile, account_id, name):
    cmd = [
        'aws', 'quicksight', 'list-analyses',
        '--profile', profile,
        '--aws-account-id', account_id,
        '--region', REGION
    ]
    output = run_aws_cli(cmd)
    for a in output['AnalysisSummaryList']:
        if a['Name'] == name:
            return a['AnalysisId']
    raise Exception(f"Analysis '{name}' not found")

def load_mapping_file(path):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    raise Exception(f"Mapping file '{path}' not found")

def get_existing_ids(profile, account_id):
    dashboards = run_aws_cli([
        'aws', 'quicksight', 'list-dashboards',
        '--profile', profile,
        '--aws-account-id', account_id,
        '--region', REGION
    ])
    analyses = run_aws_cli([
        'aws', 'quicksight', 'list-analyses',
        '--profile', profile,
        '--aws-account-id', account_id,
        '--region', REGION
    ])
    templates = run_aws_cli([
        'aws', 'quicksight', 'list-templates',
        '--profile', profile,
        '--aws-account-id', account_id,
        '--region', REGION
    ])
    ids = {d['DashboardId'] for d in dashboards.get('DashboardSummaryList', [])}
    ids.update(a['AnalysisId'] for a in analyses.get('AnalysisSummaryList', []))
    ids.update(t['TemplateId'] for t in templates.get('TemplateSummaryList', []))
    return ids

def get_next_available_id(base, existing_ids):
    version = 1
    while f"{base}-v{version}" in existing_ids:
        version += 1
    return f"{base}-v{version}"

def get_dataset_refs(profile, account_id, analysis_id, mapping_file):
    dataset_mapping = load_mapping_file(mapping_file)
    cmd = [
        'aws', 'quicksight', 'describe-analysis-definition',
        '--profile', profile,
        '--aws-account-id', account_id,
        '--analysis-id', analysis_id,
        '--region', REGION
    ]
    output = run_aws_cli(cmd)

    template_refs = []
    dashboard_refs = []

    for ref in output['Definition']['DataSetIdentifierDeclarations']:
        placeholder = ref['Identifier']
        source_arn = ref['DataSetArn']
        if placeholder not in dataset_mapping:
            raise Exception(f" Placeholder '{placeholder}' not found in mapping file.")
        target_arn = dataset_mapping[placeholder]

        template_refs.append({
            "DataSetPlaceholder": placeholder,
            "DataSetArn": source_arn
        })
        dashboard_refs.append({
            "DataSetPlaceholder": placeholder,
            "DataSetArn": target_arn
        })

    return template_refs, dashboard_refs

def get_analysis_theme_arn(profile, account_id, analysis_id):
    """Describe the source analysis and return its ThemeArn (or None if not set)."""
    try:
        output = run_aws_cli([
            'aws', 'quicksight', 'describe-analysis',
            '--profile', profile,
            '--aws-account-id', account_id,
            '--analysis-id', analysis_id,
            '--region', REGION
        ])
        theme_arn = output.get('Analysis', {}).get('ThemeArn')
        if theme_arn:
            print(f" Source analysis uses theme: {theme_arn}")
        else:
            print(" Source analysis has no custom theme (using default).")
        return theme_arn
    except Exception as e:
        print(f" Warning: Could not describe analysis to get theme: {e}")
        return None


def describe_theme(profile, account_id, theme_id):
    """Describe a theme and return the full Theme object."""
    output = run_aws_cli([
        'aws', 'quicksight', 'describe-theme',
        '--profile', profile,
        '--aws-account-id', account_id,
        '--theme-id', theme_id,
        '--region', REGION
    ])
    return output.get('Theme', {})


def ensure_theme_in_target(source_profile, source_account_id, target_profile, target_account_id, theme_arn):
    """
    Ensure the theme from the source account exists in the target account.
    Returns the target theme ARN to use, or None if it's a starter theme that already exists everywhere.
    """
    if not theme_arn:
        return None

    # Extract theme ID from ARN: arn:aws:quicksight:<region>:<account>:theme/<theme-id>
    theme_id = theme_arn.split('/')[-1]

    # QuickSight starter themes are available in all accounts
    starter_themes = {'CLASSIC', 'MIDNIGHT', 'SEASIDE', 'RAINIER'}
    if theme_id in starter_themes:
        target_theme_arn = f"arn:aws:quicksight:{REGION}:{target_account_id}:theme/{theme_id}"
        print(f" Theme '{theme_id}' is a starter theme - available in target account.")
        return target_theme_arn

    # Check if theme already exists in target account
    target_theme_arn = f"arn:aws:quicksight:{REGION}:{target_account_id}:theme/{theme_id}"
    try:
        run_aws_cli([
            'aws', 'quicksight', 'describe-theme',
            '--profile', target_profile,
            '--aws-account-id', target_account_id,
            '--theme-id', theme_id,
            '--region', REGION
        ])
        print(f" Theme '{theme_id}' already exists in target account.")
        return target_theme_arn
    except Exception:
        pass  # Theme doesn't exist in target - we'll create it

    # Describe the source theme to get its configuration
    print(f" Theme '{theme_id}' not found in target. Migrating theme...")
    try:
        source_theme = describe_theme(source_profile, source_account_id, theme_id)
        theme_config = source_theme.get('Version', {}).get('Configuration')
        theme_name = source_theme.get('Name', theme_id)
        base_theme_id = source_theme.get('Version', {}).get('BaseThemeId', 'CLASSIC')

        if not theme_config:
            print(f" Warning: Could not retrieve theme configuration. Skipping theme migration.")
            return None

        # Create the theme in the target account
        run_aws_cli([
            'aws', 'quicksight', 'create-theme',
            '--profile', target_profile,
            '--aws-account-id', target_account_id,
            '--theme-id', theme_id,
            '--name', theme_name,
            '--region', REGION,
            '--base-theme-id', base_theme_id,
            '--configuration', json.dumps(theme_config)
        ])
        print(f" Theme '{theme_id}' created in target account.")
        return target_theme_arn

    except Exception as e:
        if "ResourceExistsException" in str(e):
            print(f" Theme '{theme_id}' already exists in target (race condition). Using it.")
            return target_theme_arn
        print(f" Warning: Failed to migrate theme: {e}")
        print(" Continuing migration without theme.")
        return None


def create_template(profile, account_id, analysis_id, dataset_refs, template_id, template_name):
    source_entity = {
        "SourceAnalysis": {
            "Arn": f"arn:aws:quicksight:{REGION}:{account_id}:analysis/{analysis_id}",
            "DataSetReferences": dataset_refs
        }
    }

    try:
        run_aws_cli([
            'aws', 'quicksight', 'create-template',
            '--profile', profile,
            '--aws-account-id', account_id,
            '--template-id', template_id,
            '--region', REGION,
            '--name', template_name,
            '--source-entity', json.dumps(source_entity)
        ])
        print(f" Template '{template_id}' created.")
    except Exception as e:
        if "ResourceExistsException" in str(e):
            print(f" Template '{template_id}' already exists. Updating instead...")
            run_aws_cli([
                'aws', 'quicksight', 'update-template',
                '--profile', profile,
                '--aws-account-id', account_id,
                '--template-id', template_id,
                '--region', REGION,
                '--source-entity', json.dumps(source_entity)
            ])
            print(f" Template '{template_id}' updated.")
        else:
            raise

def grant_template_access(profile, source_account_id, target_account_id, template_id):
    cmd = [
        'aws', 'quicksight', 'update-template-permissions',
        '--profile', profile,
        '--aws-account-id', source_account_id,
        '--template-id', template_id,
        '--region', REGION,
        '--grant-permissions', f"Principal=arn:aws:iam::{target_account_id}:root,Actions=quicksight:DescribeTemplate,quicksight:DescribeTemplateAlias,quicksight:UpdateTemplate,quicksight:DeleteTemplate"
    ]
    run_aws_cli(cmd)

def create_analysis(profile, account_id, source_account_id, dataset_refs, analysis_id, analysis_name, template_id, theme_arn=None):
    cmd = [
        'aws', 'quicksight', 'create-analysis',
        '--profile', profile,
        '--aws-account-id', account_id,
        '--analysis-id', analysis_id,
        '--name', analysis_name,
        '--region', REGION,
        '--source-entity', json.dumps({
            "SourceTemplate": {
                "Arn": f"arn:aws:quicksight:{REGION}:{source_account_id}:template/{template_id}",
                "DataSetReferences": dataset_refs
            }
        })
    ]
    if theme_arn:
        cmd += ['--theme-arn', theme_arn]

    try:
        run_aws_cli(cmd)
        print(f" Analysis '{analysis_id}' created.")
    except Exception as e:
        if "ResourceExistsException" in str(e):
            print(f" Analysis '{analysis_id}' already exists. Skipping creation.")
        else:
            raise

def create_dashboard(profile, account_id, source_account_id, dataset_refs, dashboard_id, dashboard_name, template_id, theme_arn=None):
    cmd = [
        'aws', 'quicksight', 'create-dashboard',
        '--profile', profile,
        '--aws-account-id', account_id,
        '--dashboard-id', dashboard_id,
        '--region', REGION,
        '--name', dashboard_name,
        '--source-entity', json.dumps({
            "SourceTemplate": {
                "Arn": f"arn:aws:quicksight:{REGION}:{source_account_id}:template/{template_id}",
                "DataSetReferences": dataset_refs
            }
        })
    ]
    if theme_arn:
        cmd += ['--theme-arn', theme_arn]
    run_aws_cli(cmd)

def share_dashboard_with_user(profile, account_id, dashboard_id, username):
    full_access_actions = [
        "quicksight:DescribeDashboard",
        "quicksight:ListDashboardVersions",
        "quicksight:UpdateDashboardPermissions",
        "quicksight:QueryDashboard",
        "quicksight:UpdateDashboard",
        "quicksight:DeleteDashboard",
        "quicksight:UpdateDashboardPublishedVersion",
        "quicksight:DescribeDashboardPermissions"
    ]

    cmd = [
        'aws', 'quicksight', 'update-dashboard-permissions',
        '--profile', profile,
        '--aws-account-id', account_id,
        '--dashboard-id', dashboard_id,
        '--region', REGION,
        '--grant-permissions', json.dumps({
            "Principal": f"arn:aws:quicksight:{REGION}:{account_id}:user/default/{username}",
            "Actions": full_access_actions
        })
    ]
    run_aws_cli(cmd)
    print(f" Shared dashboard '{dashboard_id}' with user '{username}'.")

def share_analysis_with_user(profile, account_id, analysis_id, username):
    actions = [
        "quicksight:RestoreAnalysis",
        "quicksight:UpdateAnalysisPermissions",
        "quicksight:DeleteAnalysis",
        "quicksight:QueryAnalysis",
        "quicksight:DescribeAnalysisPermissions",
        "quicksight:DescribeAnalysis",
        "quicksight:UpdateAnalysis"
    ]
    cmd = [
        'aws', 'quicksight', 'update-analysis-permissions',
        '--profile', profile,
        '--aws-account-id', account_id,
        '--analysis-id', analysis_id,
        '--region', REGION,
        '--grant-permissions', json.dumps({
            "Principal": f"arn:aws:quicksight:{REGION}:{account_id}:user/default/{username}",
            "Actions": actions
        })
    ]
    run_aws_cli(cmd)
    print(f" Shared analysis '{analysis_id}' with user '{username}'.")


def main(analysis_name, dashboard_name, mapping_file,
         source_profile, target_profile,
         confirm=False):
    source_account_id, _ = get_profile_info(source_profile)
    target_account_id, target_username = get_profile_info(target_profile)
    source = {'profile': source_profile, 'account_id': source_account_id}
    target = {'profile': target_profile, 'account_id': target_account_id}

    if not confirm:
        print(f"\nMigrating from {source_profile} -> {target_profile}. Do you want to continue (Y/N)?", end=" ")
        user_input = input().strip().lower()
        if user_input != 'y':
            print("Migration cancelled.")
            return

    validate_profile(source['profile'])
    validate_profile(target['profile'])

    analysis_id = get_analysis_id_by_name(source['profile'], source['account_id'], analysis_name)
    template_refs, dashboard_refs = get_dataset_refs(source['profile'], source['account_id'], analysis_id, mapping_file)


    existing_ids = get_existing_ids(target['profile'], target['account_id'])
    dashboard_id = get_next_available_id(sanitize_id(dashboard_name), existing_ids)
    analysis_id_target = get_next_available_id(f"{sanitize_id(dashboard_name)}-analysis", existing_ids)
    template_id = get_next_available_id(f"{sanitize_id(dashboard_name)}-template", existing_ids)

    template_name = f"{dashboard_name} Template"
    datestamp = datetime.datetime.now().strftime("%Y%m%d_%H_%M_%S")
    analysis_name_target = f"{dashboard_name}_{datestamp}"

    print(f"\n Starting dashboard migration: {source_profile} -> {target_profile}")

    # Migrate theme if the source analysis uses one
    source_theme_arn = get_analysis_theme_arn(source['profile'], source['account_id'], analysis_id)
    target_theme_arn = ensure_theme_in_target(
        source['profile'], source['account_id'],
        target['profile'], target['account_id'],
        source_theme_arn
    )

    create_template(source['profile'], source['account_id'], analysis_id, template_refs, template_id, template_name)
    time.sleep(5)
    grant_template_access(source['profile'], source['account_id'], target['account_id'], template_id)
    time.sleep(10)
    create_analysis(target['profile'], target['account_id'], source['account_id'], dashboard_refs, analysis_id_target, analysis_name_target, template_id, theme_arn=target_theme_arn)
    share_analysis_with_user(target['profile'], target['account_id'], analysis_id_target, target_username)
    create_dashboard(target['profile'], target['account_id'], source['account_id'], dashboard_refs, dashboard_id, dashboard_name, template_id, theme_arn=target_theme_arn)
    share_dashboard_with_user(target['profile'], target['account_id'], dashboard_id, target_username)

    print("\n Dashboard and analysis migration completed successfully!")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='QuickSight Dashboard Migrator')
    parser.add_argument('--analysis-name', required=True, help='Name of the analysis to migrate')
    parser.add_argument('--dashboard-name', required=True, help='Name for the new dashboard')
    parser.add_argument('--mapping-file', default='dataset_mapping.json', help='Path to the dataset mapping JSON file')
    parser.add_argument('--source-profile', required=True, help='AWS profile for the source account')
    parser.add_argument('--target-profile', required=True, help='AWS profile for the target account')
    parser.add_argument('--confirm', action='store_true', help='Automatically confirm migration (skip interactive prompt)')
    args = parser.parse_args()
    main(
        args.analysis_name, args.dashboard_name, args.mapping_file,
        args.source_profile, args.target_profile,
        confirm=args.confirm
    )
