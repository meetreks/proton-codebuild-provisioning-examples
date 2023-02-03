#!/usr/bin/env python3

import boto3
import yaml
import typer
from rich import print
from os import getenv

app = typer.Typer()
client = boto3.client('proton')
EXPECTED_DEPLOYMENT_STATUS = ['IN_PROGRESS','DELETE_IN_PROGRESS','DELETE_COMPLETE','CANCELLING']

def collect_metadata(environment_name: str):
    environment = client.get_environment(name=environment_name)
    specFile = yaml.safe_load(environment['environment']['spec'])
    namespaces = specFile['spec'].get('namespaces', [])
    return environment, specFile, namespaces

def validate_ns_exist(namespace: str, namespaces: list, action: str):
    """
    Return true if no action is required (on provisioning if namespace already exists)
    """
    if namespace in namespaces:
        if action == 'delete':
            return False
        else:
            return True
    else:
        return False

def prepare_spec(namespaces, spec):
    spec['spec']['namespaces'] = namespaces
    return yaml.dump(spec)

def env_waiter(env_name, waiter_delay=10, max_attempts=60):
        print("Checking/waiting for available status for environment")
        waiter = client.get_waiter('environment_deployed')
        waiter.wait(
            name=env_name,
            WaiterConfig={
                'Delay': waiter_delay,
                'MaxAttempts': max_attempts
            }
        )
        print("Waiting complete")

def update_proton_environment(environment, env_name, spec):
    env_waiter(env_name)
    environment = client.get_environment(name=env_name)
    if environment['environment']['deploymentStatus'] not in EXPECTED_DEPLOYMENT_STATUS:
        client.update_environment(
            deploymentType='CURRENT_VERSION',
            description='Automated update via EKS namespace vending',
            name=env_name,
            spec=spec
        )
    else:
        raise Exception("Environment was stuck in a deployment state longer than acceptable. Please investigate.")

    env_waiter(env_name)
    print("Deployment complete!")

def finalize_deployment(nsName, action):
    if action == 'create':
        kubectlCommand = "aws eks update-kubeconfig --name cluster-name-here --region region-here --role-arn role-arn-here"
        client.notify_resource_deployment_status_change(
            resourceArn=getenv('RESOURCE_ARN'),
            outputs=[
              {
                "key": "NamespaceName",
                "valueString": nsName
              },
              {
                "key": "KubectlConfiguration",
                "valueString": kubectlCommand
              }
            ],
            status='SUCCEEDED'
        )
    else:
        print("Complete")

def proton_environment_deployment(namespace_name, environment_name, action):
    environment, spec, ns = collect_metadata(environment_name)
    
    ns_exists = validate_ns_exist(namespace_name, ns, action)

    if action == 'create' and ns_exists is False:
        ns.append(namespace_name)
        text_action = "Creating"
    elif action == 'delete' and ns_exists is False:
        ns.remove(namespace_name)
        text_action = 'Deleting'
    else:
        text_action = "Updating"

    updated_spec = prepare_spec(ns, spec)
    print(f"{text_action} \"{namespace_name}\" namespace for environment \"{environment_name}\"")
    update_proton_environment(environment, environment_name, updated_spec)
    finalize_deployment(namespace_name, action)

@app.command()
def create_namespace(
    namespace_name: str = typer.Argument(..., help="Kubernetes namespace name"), 
    environment_name: str = typer.Argument(..., help="Environment to deploy namespace on")):
    """
    Create a namespace on the EKS environment managed via AWS Proton
    """
    proton_environment_deployment(namespace_name, environment_name, "create")

@app.command()
def delete_namespace(
    namespace_name: str = typer.Argument(..., help="Kubernetes namespace name"), 
    environment_name: str = typer.Argument(..., help="Environment to deploy namespace on")):
    """
    Create a namespace on the EKS environment managed via AWS Proton
    """
    proton_environment_deployment(namespace_name, environment_name, "delete")

if __name__ == "__main__":
    app()