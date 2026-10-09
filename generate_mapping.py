import json
import argparse
import subprocess
import os

REGION = 'us-west-2'

def run_aws_cli(cmd_list):
    result = subprocess.run(cmd_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise Exception(result.stderr.decode())
    return json.loads(result.stdout.decode('utf-8', errors='replace'))

def list_datasets(profile, account_id):
    cmd = [
        'aws', 'quicksight', 'list-data-sets',
        '--profile', profile,
        '--aws-account-id', account_id,
        '--region', REGION
    ]
    output = run_aws_cli(cmd)
    return {d['Name'].lower(): d['Arn'] for d in output['DataSetSummaries']}

def get_analysis_definition(profile, account_id, analysis_name):
    cmd_list = [
        'aws', 'quicksight', 'list-analyses',
        '--profile', profile,
        '--aws-account-id', account_id,
        '--region', REGION
    ]
    output = run_aws_cli(cmd_list)
    for analysis in output['AnalysisSummaryList']:
        if analysis['Name'] == analysis_name:
            analysis_id = analysis['AnalysisId']
            break
    else:
        raise Exception(f"Analysis named '{analysis_name}' not found")

    cmd = [
        'aws', 'quicksight', 'describe-analysis-definition',
        '--profile', profile,
        '--aws-account-id', account_id,
        '--analysis-id', analysis_id,
        '--region', REGION
    ]
    return run_aws_cli(cmd)

def generate_placeholder_mapping(source_profile, source_account, target_profile, target_account, analysis_name, output_file):
    print("Generating mapping from analysis placeholders...")

    target_datasets = list_datasets(target_profile, target_account)
    target_names_to_arn = {name.lower(): arn for name, arn in target_datasets.items()}

    analysis_def = get_analysis_definition(source_profile, source_account, analysis_name)

    mapping = {}
    unmatched = {}

    for ref in analysis_def['Definition']['DataSetIdentifierDeclarations']:
        placeholder = ref['Identifier']
        dataset_arn = ref['DataSetArn']
        dataset_id = dataset_arn.split('/')[-1]

        cmd = [
            'aws', 'quicksight', 'describe-data-set',
            '--profile', source_profile,
            '--aws-account-id', source_account,
            '--data-set-id', dataset_id,
            '--region', REGION
        ]
        dataset_info = run_aws_cli(cmd)
        source_name = dataset_info['DataSet']['Name'].lower()

        if source_name in target_names_to_arn:
            mapping[placeholder] = target_names_to_arn[source_name]
        else:
            unmatched[placeholder] = source_name
            print(f" Warning: No matching dataset in target for source dataset '{source_name}' (placeholder '{placeholder}')")

    with open(output_file, 'w') as f:
        json.dump(mapping, f, indent=2)

    print(f"\n Mapping file saved to {output_file}. {len(mapping)} mappings created.")

    if unmatched:
        print("\n The following placeholders were not matched:")
        for placeholder, name in unmatched.items():
            print(f"  - {placeholder}  (source dataset name: '{name}')")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate QuickSight Placeholder Mapping')
    parser.add_argument('--source-profile', required=True)
    parser.add_argument('--source-account', required=True)
    parser.add_argument('--target-profile', required=True)
    parser.add_argument('--target-account', required=True)
    parser.add_argument('--analysis-name', required=True, help='Name of the analysis to extract placeholders from')
    parser.add_argument('--output-file', default='dataset_mapping.json', help='Output mapping JSON file')
    args = parser.parse_args()

    generate_placeholder_mapping(
        args.source_profile,
        args.source_account,
        args.target_profile,
        args.target_account,
        args.analysis_name,
        args.output_file
    )
