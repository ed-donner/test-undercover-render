"""UnderCover's pieces from Day 3 on AWS, brought back for today's Lab 2 in a few calls.

Each function does what a part of Day 3's lab did, in the same way: it creates what's
missing and updates what's already there. The app and the context layer go on Lambda,
the Gateway gets both as targets with the Policy enforced, and the Memory gets its two
strategies. Everything is named undercover... and tagged project=undercover, and
tear_down deletes the AgentCore pieces by name, keeping the two functions.
"""

import json
import shutil
import subprocess
import time
from pathlib import Path

import boto3
import requests

REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / "build"

APP_FUNCTION = "undercover-app"
APP_ROLE_NAME = "undercover-app-role"
CONTEXT_FUNCTION = "undercover-context"
CONTEXT_ROLE_NAME = "undercover-context-role"
KEY_PROVIDER_NAME = "undercover-app-key"
GATEWAY_ROLE_NAME = "undercover-gateway-role"
GATEWAY_NAME = "undercover-gateway"
APP_TARGET = "undercover-app"
CONTEXT_TARGET = "undercover-context"
ENGINE_NAME = "undercover_policy_engine"
MEMORY_NAME = "undercover_memory"
PROJECT_TAG = {"project": "undercover"}
LINUX = ["--python-platform", "x86_64-manylinux2014", "--python-version", "3.12", "--only-binary", ":all:"]

session = boto3.Session()
region = session.region_name
account = session.client("sts").get_caller_identity()["Account"]
lambda_client = session.client("lambda")
iam = session.client("iam")
logs = session.client("logs")
agentcore = session.client("bedrock-agentcore-control")
cloudformation = session.client("cloudformation")


# The app and the context layer on Lambda


def package(name, group, folders):
    """Zip folders of the repo with a dependency group's packages for Lambda."""
    folder = BUILD / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    requirements = BUILD / f"{name}-requirements.txt"
    export = ["uv", "export", "--only-group", group, "--no-hashes", "--no-emit-project", "--quiet", "--output-file", str(requirements)]
    subprocess.run(export, cwd=REPO, check=True)
    subprocess.run(["uv", "pip", "install", "--quiet", "--target", str(folder), *LINUX, "-r", str(requirements)], cwd=REPO, check=True)
    for source, target in folders.items():
        shutil.copytree(REPO / source, folder / target, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    zip_path = Path(shutil.make_archive(str(BUILD / name), "zip", folder))
    print(f"{zip_path.name}: {zip_path.stat().st_size / 1_000_000:.1f} MB (Lambda takes up to 50 MB)")
    return zip_path


def make_log_group(name):
    """Create a log group that keeps logs for 7 days."""
    try:
        logs.create_log_group(logGroupName=name)
        print(f"Created log group {name}")
    except logs.exceptions.ResourceAlreadyExistsException:
        print(f"Log group {name} already exists")
    logs.put_retention_policy(logGroupName=name, retentionInDays=7)


def make_function_role(role_name, log_group, description):
    """Create a role that lets Lambda run a function and write to its log group, and nothing else."""
    lambda_trust = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}],
    }
    try:
        role = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(lambda_trust),
            Description=description,
            Tags=[{"Key": key, "Value": value} for key, value in PROJECT_TAG.items()],
        )["Role"]
        print(f"Created role {role_name}")
    except iam.exceptions.EntityAlreadyExistsException:
        role = iam.get_role(RoleName=role_name)["Role"]
        print(f"Role {role_name} already exists")
    logging_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": f"arn:aws:logs:{region}:{account}:log-group:{log_group}:*",
            }
        ],
    }
    iam.put_role_policy(RoleName=role_name, PolicyName=f"{role_name}-logging", PolicyDocument=json.dumps(logging_policy))
    return role


def deploy_function(name, role, zip_path, settings):
    """Create the function, waiting for a new role to reach Lambda, or update it in place."""
    zip_bytes = zip_path.read_bytes()
    try:
        lambda_client.get_function(FunctionName=name)
        lambda_client.update_function_code(FunctionName=name, ZipFile=zip_bytes)
        lambda_client.get_waiter("function_updated_v2").wait(FunctionName=name)
        lambda_client.update_function_configuration(FunctionName=name, Role=role["Arn"], **settings)
        lambda_client.get_waiter("function_updated_v2").wait(FunctionName=name)
        print(f"Updated function {name}")
    except lambda_client.exceptions.ResourceNotFoundException:
        for attempt in range(10):
            try:
                lambda_client.create_function(FunctionName=name, Role=role["Arn"], Code={"ZipFile": zip_bytes}, Tags=PROJECT_TAG, **settings)
                break
            except lambda_client.exceptions.InvalidParameterValueException:
                print("Waiting for the new role to reach Lambda")
                time.sleep(3)
        lambda_client.get_waiter("function_active_v2").wait(FunctionName=name)
        print(f"Created function {name}")
    return lambda_client.get_function(FunctionName=name)["Configuration"]["FunctionArn"]


def function_url(name, auth_type):
    """The function's URL, made the first time."""
    try:
        url = lambda_client.create_function_url_config(FunctionName=name, AuthType=auth_type)["FunctionUrl"]
    except lambda_client.exceptions.ResourceConflictException:
        url = lambda_client.get_function_url_config(FunctionName=name)["FunctionUrl"]
    return url.rstrip("/")


def deploy_app(environment):
    """Package the app with the dashboard built by npm run build, and deploy it on Lambda
    with its public Function URL and the environment given, as on Day 3."""
    zip_path = package("lambda", "server", {"backend": "backend", "data": "data", "dashboard/dist": "dashboard/dist"})
    log_group = f"/aws/lambda/{APP_FUNCTION}"
    make_log_group(log_group)
    role = make_function_role(APP_ROLE_NAME, log_group, "The role the UnderCover app runs as on Lambda")
    settings = {
        "Runtime": "python3.12",
        "Handler": "backend.main.handler",
        "Timeout": 30,
        "MemorySize": 1024,
        "Environment": {"Variables": environment},
    }
    deploy_function(APP_FUNCTION, role, zip_path, settings)
    url = function_url(APP_FUNCTION, "NONE")
    public_access = [
        {"StatementId": "public-url", "Action": "lambda:InvokeFunctionUrl", "FunctionUrlAuthType": "NONE"},
        {"StatementId": "public-invoke", "Action": "lambda:InvokeFunction", "InvokedViaFunctionUrl": True},
    ]
    for statement in public_access:
        try:
            lambda_client.add_permission(FunctionName=APP_FUNCTION, Principal="*", **statement)
        except lambda_client.exceptions.ResourceConflictException:
            pass
    return url


def deploy_context():
    """Package the context layer and deploy it on Lambda behind an IAM Function URL, as on Day 3."""
    zip_path = package("context", "context", {"context": "context"})
    log_group = f"/aws/lambda/{CONTEXT_FUNCTION}"
    make_log_group(log_group)
    role = make_function_role(CONTEXT_ROLE_NAME, log_group, "The role UnderCover's context layer runs as on Lambda")
    settings = {"Runtime": "python3.12", "Handler": "context.server.handler", "Timeout": 30, "MemorySize": 512}
    deploy_function(CONTEXT_FUNCTION, role, zip_path, settings)
    return function_url(CONTEXT_FUNCTION, "AWS_IAM")


# The Gateway with both targets and the Policy


def wait_for(get_resource, label):
    """Wait while an AgentCore resource is being created or updated, then print its status."""
    while True:
        resource = get_resource()
        if resource["status"] not in ("CREATING", "UPDATING", "SYNCHRONIZING"):
            break
        time.sleep(3)
    print(f"{label}: {resource['status']}")
    for reason in resource.get("statusReasons", []):
        print(f"  {reason}")
    return resource


def find_key_providers():
    """The API key credential providers named undercover-..."""
    pages = agentcore.get_paginator("list_api_key_credential_providers").paginate()
    return [p["name"] for page in pages for p in page["credentialProviders"] if p["name"].startswith("undercover-")]


def find_gateways():
    """The gateways named undercover-gateway."""
    pages = agentcore.get_paginator("list_gateways").paginate()
    return [g for page in pages for g in page["items"] if g["name"].startswith(GATEWAY_NAME)]


def find_targets(gateway_id):
    """The Gateway's targets."""
    pages = agentcore.get_paginator("list_gateway_targets").paginate(gatewayIdentifier=gateway_id)
    return [t for page in pages for t in page["items"]]


def find_policy_engines():
    """The policy engines named undercover..."""
    pages = agentcore.get_paginator("list_policy_engines").paginate()
    return [e for page in pages for e in page["policyEngines"] if e["name"].startswith("undercover")]


def find_policies(engine_id):
    """The policies in a policy engine."""
    pages = agentcore.get_paginator("list_policies").paginate(policyEngineId=engine_id)
    return [p for page in pages for p in page["policies"]]


def find_memories():
    """The memories named undercover_memory, leaving out any being deleted."""
    pages = agentcore.get_paginator("list_memories").paginate()
    return [m for page in pages for m in page["memories"] if m["id"].startswith(MEMORY_NAME) and m["status"] != "DELETING"]


def find_roles():
    """The IAM roles named undercover..."""
    pages = iam.get_paginator("list_roles").paginate()
    return [r["RoleName"] for page in pages for r in page["Roles"] if r["RoleName"].startswith("undercover")]


def put_key_provider(api_key):
    """The app's API key in AgentCore Identity, for the Gateway to send."""
    if KEY_PROVIDER_NAME in find_key_providers():
        agentcore.update_api_key_credential_provider(name=KEY_PROVIDER_NAME, apiKey=api_key)
        print(f"Credential provider {KEY_PROVIDER_NAME} already exists, key updated")
    else:
        agentcore.create_api_key_credential_provider(name=KEY_PROVIDER_NAME, apiKey=api_key, tags=PROJECT_TAG)
        print(f"Created credential provider {KEY_PROVIDER_NAME}")
    return agentcore.get_api_key_credential_provider(name=KEY_PROVIDER_NAME)


def make_gateway_role(provider, context_arn):
    """The Gateway's role: it fetches the app's key and invokes the context layer."""
    gateway_trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account},
                    "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock-agentcore:{region}:{account}:gateway/{GATEWAY_NAME}-*"},
                },
            }
        ],
    }
    try:
        role = iam.create_role(
            RoleName=GATEWAY_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(gateway_trust),
            Description="The role the UnderCover gateway runs as",
            Tags=[{"Key": key, "Value": value} for key, value in PROJECT_TAG.items()],
        )["Role"]
        print(f"Created role {GATEWAY_ROLE_NAME}")
    except iam.exceptions.EntityAlreadyExistsException:
        role = iam.get_role(RoleName=GATEWAY_ROLE_NAME)["Role"]
        print(f"Role {GATEWAY_ROLE_NAME} already exists")

    provider_arn = provider["credentialProviderArn"]
    workload_directory = f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default"
    workload_identity = [workload_directory, f"{workload_directory}/workload-identity/{GATEWAY_NAME}-*"]
    token_vault = provider_arn.split("/apikeycredentialprovider/")[0]
    api_key_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": "bedrock-agentcore:GetWorkloadAccessToken", "Resource": workload_identity},
            {"Effect": "Allow", "Action": "bedrock-agentcore:GetResourceApiKey", "Resource": [provider_arn, token_vault, *workload_identity]},
            {"Effect": "Allow", "Action": "secretsmanager:GetSecretValue", "Resource": provider["apiKeySecretArn"]["secretArn"]},
        ],
    }
    context_policy = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": ["lambda:InvokeFunctionUrl", "lambda:InvokeFunction"], "Resource": context_arn}],
    }
    iam.put_role_policy(RoleName=GATEWAY_ROLE_NAME, PolicyName="undercover-gateway-api-key", PolicyDocument=json.dumps(api_key_policy))
    iam.put_role_policy(RoleName=GATEWAY_ROLE_NAME, PolicyName="undercover-gateway-context", PolicyDocument=json.dumps(context_policy))
    return role


def make_gateway(role):
    """Create the Gateway, waiting for its new role to reach AgentCore, unless it exists."""
    existing = find_gateways()
    if existing:
        gateway_id = existing[0]["gatewayId"]
    else:
        for attempt in range(10):
            try:
                gateway_id = agentcore.create_gateway(
                    name=GATEWAY_NAME,
                    description="UnderCover's systems as tools for the claim agent",
                    roleArn=role["Arn"],
                    protocolType="MCP",
                    authorizerType="AWS_IAM",
                    exceptionLevel="DEBUG",
                    tags=PROJECT_TAG,
                )["gatewayId"]
                break
            except agentcore.exceptions.ValidationException as error:
                if "role" not in str(error).lower():
                    raise
                print("Waiting for the new role to reach AgentCore")
                time.sleep(3)
    return wait_for(lambda: agentcore.get_gateway(gatewayIdentifier=gateway_id), f"Gateway {gateway_id}")


def put_target(gateway_id, settings):
    """Create a target, or update it in place, and try again while the Gateway's role can't be used yet."""
    for attempt in range(20):
        existing = [t for t in find_targets(gateway_id) if t["name"] == settings["name"]]
        if existing:
            target_id = existing[0]["targetId"]
            agentcore.update_gateway_target(gatewayIdentifier=gateway_id, targetId=target_id, **settings)
        else:
            target_id = agentcore.create_gateway_target(gatewayIdentifier=gateway_id, **settings)["targetId"]
        target = wait_for(lambda: agentcore.get_gateway_target(gatewayIdentifier=gateway_id, targetId=target_id), f"Target {settings['name']}")
        reasons = " ".join(target.get("statusReasons", []))
        if target["status"] == "READY" or ("role" not in reasons and "Authorization" not in reasons):
            return target
        print("Waiting for the Gateway's role to reach AgentCore")
        time.sleep(10)
    raise RuntimeError("AgentCore could not use the role")


def agent_api(app_url, api_key):
    """The app's API document for the claim agent, with the app's address as its server."""
    for attempt in range(5):
        response = requests.get(f"{app_url}/api/agent/openapi.json", headers={"X-API-Key": api_key}, timeout=60)
        if response.ok:
            break
        time.sleep(3)
    response.raise_for_status()
    document = response.json()
    document["servers"] = [{"url": app_url}]
    return document


def put_targets(gateway_id, app_url, context_url, provider, api_key):
    """The app's operations for the claim agent with its key, and the context layer's tools."""
    put_target(
        gateway_id,
        {
            "name": APP_TARGET,
            "description": "The UnderCover app's routes for the claim agent",
            "targetConfiguration": {"mcp": {"openApiSchema": {"inlinePayload": json.dumps(agent_api(app_url, api_key))}}},
            "credentialProviderConfigurations": [
                {
                    "credentialProviderType": "API_KEY",
                    "credentialProvider": {
                        "apiKeyCredentialProvider": {
                            "providerArn": provider["credentialProviderArn"],
                            "credentialParameterName": "X-API-Key",
                            "credentialLocation": "HEADER",
                        }
                    },
                }
            ],
        },
    )
    put_target(
        gateway_id,
        {
            "name": CONTEXT_TARGET,
            "description": "UnderCover's context layer: definitions, plans, rules, reference data and documents",
            "targetConfiguration": {"mcp": {"mcpServer": {"endpoint": f"{context_url}/mcp"}}},
            "credentialProviderConfigurations": [
                {
                    "credentialProviderType": "GATEWAY_IAM_ROLE",
                    "credentialProvider": {"iamCredentialProvider": {"service": "lambda", "region": region}},
                }
            ],
        },
    )


def permit(target, gateway_arn):
    """A Cedar policy that permits every tool on one target."""
    return f"""permit(
  principal is AgentCore::IamEntity,
  action in AgentCore::Action::"{target}",
  resource == AgentCore::Gateway::"{gateway_arn}"
);"""


def payment_limit(gateway_arn):
    """The Cedar policy that forbids any payment over $1,000."""
    return f"""forbid(
  principal is AgentCore::IamEntity,
  action == AgentCore::Action::"{APP_TARGET}___pay_claim",
  resource == AgentCore::Gateway::"{gateway_arn}"
)
when {{
  context.input.amount.greaterThan(decimal("1000.00"))
}};"""


def enforce_policy(gateway, role):
    """The policy engine, enforced on the Gateway, with a permit for each target's tools
    and the forbid on payments over $1,000."""
    existing = [e for e in find_policy_engines() if e["name"] == ENGINE_NAME]
    if existing:
        engine_id = existing[0]["policyEngineId"]
    else:
        engine_id = agentcore.create_policy_engine(name=ENGINE_NAME, description="Rules for the UnderCover gateway", tags=PROJECT_TAG)["policyEngineId"]
    engine = wait_for(lambda: agentcore.get_policy_engine(policyEngineId=engine_id), f"Policy engine {engine_id}")
    engine_arn = engine["policyEngineArn"]
    gateway_id, gateway_arn = gateway["gatewayId"], gateway["gatewayArn"]

    policy_engine_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": "bedrock-agentcore:GetPolicyEngine", "Resource": engine_arn},
            {
                "Effect": "Allow",
                "Action": ["bedrock-agentcore:AuthorizeAction", "bedrock-agentcore:PartiallyAuthorizeActions"],
                "Resource": [engine_arn, gateway_arn],
            },
        ],
    }
    iam.put_role_policy(RoleName=GATEWAY_ROLE_NAME, PolicyName="undercover-gateway-policy-engine", PolicyDocument=json.dumps(policy_engine_policy))

    for attempt in range(20):
        try:
            agentcore.update_gateway(
                gatewayIdentifier=gateway_id,
                name=GATEWAY_NAME,
                description=gateway["description"],
                roleArn=role["Arn"],
                protocolType="MCP",
                authorizerType="AWS_IAM",
                exceptionLevel="DEBUG",
                policyEngineConfiguration={"arn": engine_arn, "mode": "ENFORCE"},
            )
            break
        except agentcore.exceptions.ValidationException as error:
            if "GetPolicyEngine" not in str(error):
                raise
            print("Waiting for the role's new permission to reach AgentCore")
            time.sleep(5)
    wait_for(lambda: agentcore.get_gateway(gatewayIdentifier=gateway_id), f"Gateway {gateway_id}")

    policies = {
        "undercover_allow_app_tools": permit(APP_TARGET, gateway_arn),
        "undercover_allow_context_tools": permit(CONTEXT_TARGET, gateway_arn),
        "undercover_payment_limit": payment_limit(gateway_arn),
    }
    existing = {p["name"]: p for p in find_policies(engine_id)}
    for name, statement in policies.items():
        if name in existing:
            policy_id = existing[name]["policyId"]
        else:
            policy_id = agentcore.create_policy(policyEngineId=engine_id, name=name, definition={"cedar": {"statement": statement}})["policyId"]
        wait_for(lambda: agentcore.get_policy(policyEngineId=engine_id, policyId=policy_id), f"Policy {name}")


def create_gateway(app_url, context_url, api_key):
    """The Gateway with the app and the context layer as its targets and the Policy
    enforced, as on Day 3. Returns the Gateway."""
    provider = put_key_provider(api_key)
    context_arn = lambda_client.get_function(FunctionName=CONTEXT_FUNCTION)["Configuration"]["FunctionArn"]
    role = make_gateway_role(provider, context_arn)
    gateway = make_gateway(role)
    put_targets(gateway["gatewayId"], app_url, context_url, provider, api_key)
    enforce_policy(gateway, role)
    return gateway


# The Memory


def create_memory():
    """The agent's Memory with a Semantic and a Summary strategy, as on Day 3, which takes
    about two and a half minutes to create. Returns its id."""
    existing = find_memories()
    if existing:
        memory_id = existing[0]["id"]
    else:
        memory_id = agentcore.create_memory(
            name=MEMORY_NAME,
            description="The UnderCover Agent's memory of each customer",
            eventExpiryDuration=7,
            memoryStrategies=[
                {"semanticMemoryStrategy": {"name": "customer_facts", "namespaceTemplates": ["/customers/{actorId}/facts/"]}},
                {"summaryMemoryStrategy": {"name": "claim_summaries", "namespaceTemplates": ["/customers/{actorId}/claims/{sessionId}/"]}},
            ],
            tags=PROJECT_TAG,
        )["memory"]["id"]
    while (memory := agentcore.get_memory(memoryId=memory_id)["memory"])["status"] == "CREATING":
        time.sleep(10)
    print(f"Memory {memory_id}: {memory['status']}")
    return memory_id


# The agent's runtime


def find_runtimes(prefix):
    """The runtimes whose names start with a prefix."""
    runtimes = agentcore.list_agent_runtimes()["agentRuntimes"]
    return [r for r in runtimes if r["agentRuntimeName"].startswith(prefix)]


# What's there, and the teardown


def find_stacks():
    """The agent's stack and the CDK bootstrap, if they exist."""
    pages = cloudformation.get_paginator("describe_stacks").paginate()
    names = [stack["StackName"] for page in pages for stack in page["Stacks"]]
    return [name for name in names if name.startswith(("AgentCore-undercover", "CDKToolkit"))]


def show_resources():
    """Print the Lambda functions, AgentCore pieces and IAM roles named undercover..."""
    lambda_pages = lambda_client.get_paginator("list_functions").paginate()
    found = {
        "Lambda functions": [f["FunctionName"] for page in lambda_pages for f in page["Functions"] if f["FunctionName"].startswith("undercover")],
        "Gateways": [g["name"] for g in find_gateways()],
        "Policy engines": [e["name"] for e in find_policy_engines()],
        "API key providers": find_key_providers(),
        "Memories": [m["id"] for m in find_memories()],
        "Runtimes": [r["agentRuntimeName"] for r in find_runtimes("undercover")],
        "Stacks": find_stacks(),
        "IAM roles": find_roles(),
    }
    for label, names in found.items():
        print(f"{label + ':':<20}{', '.join(names) or 'none'}")


def tear_down():
    """Delete the Gateway with its targets, the policy engine with its policies, the app's
    key in AgentCore Identity, the Memory and the Gateway's role, keeping the two functions."""
    for summary in find_gateways():
        for target in find_targets(summary["gatewayId"]):
            agentcore.delete_gateway_target(gatewayIdentifier=summary["gatewayId"], targetId=target["targetId"])
            print(f"Deleted target {target['name']}")
        while find_targets(summary["gatewayId"]):
            time.sleep(3)
        agentcore.delete_gateway(gatewayIdentifier=summary["gatewayId"])
        print(f"Deleted gateway {summary['name']}")

    for summary in find_policy_engines():
        for policy in find_policies(summary["policyEngineId"]):
            agentcore.delete_policy(policyEngineId=summary["policyEngineId"], policyId=policy["policyId"])
            print(f"Deleted policy {policy['name']}")
        while find_policies(summary["policyEngineId"]):
            time.sleep(3)
        agentcore.delete_policy_engine(policyEngineId=summary["policyEngineId"])
        print(f"Deleted policy engine {summary['name']}")

    for name in find_key_providers():
        agentcore.delete_api_key_credential_provider(name=name)
        print(f"Deleted credential provider {name}")

    for memory in find_memories():
        agentcore.delete_memory(memoryId=memory["id"])
        print(f"Deleted memory {memory['id']}")

    if GATEWAY_ROLE_NAME in find_roles():
        delete_role(GATEWAY_ROLE_NAME)


def delete_role(role_name):
    """Delete a role and its inline policies."""
    for policy_name in iam.list_role_policies(RoleName=role_name)["PolicyNames"]:
        iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
    iam.delete_role(RoleName=role_name)
    print(f"Deleted role {role_name}")


def delete_functions():
    """Delete the app and the context layer from Lambda, with their roles and log groups."""
    for function, role_name in [(APP_FUNCTION, APP_ROLE_NAME), (CONTEXT_FUNCTION, CONTEXT_ROLE_NAME)]:
        lambda_client.delete_function(FunctionName=function)
        print(f"Deleted function {function}")
        delete_role(role_name)
        logs.delete_log_group(logGroupName=f"/aws/lambda/{function}")
        print(f"Deleted log group /aws/lambda/{function}")


def delete_bootstrap():
    """Delete the CDK bootstrap: empty its bucket, which keeps every version of each file,
    delete the CDKToolkit stack, then the bucket, which the stack leaves. Deleting the stack
    schedules its KMS key for deletion, and billing for the key stops."""
    bucket = session.resource("s3").Bucket(f"cdk-hnb659fds-assets-{account}-{region}")
    if bucket.creation_date:
        bucket.object_versions.delete()
    cloudformation.delete_stack(StackName="CDKToolkit")
    cloudformation.get_waiter("stack_delete_complete").wait(StackName="CDKToolkit")
    print("Deleted the CDKToolkit stack")
    if bucket.creation_date:
        bucket.object_versions.delete()
        bucket.delete()
        print(f"Deleted the bucket {bucket.name}")
