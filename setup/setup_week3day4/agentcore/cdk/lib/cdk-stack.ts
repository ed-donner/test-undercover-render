import { AgentCoreApplication, type AgentCoreApplicationProps } from '@aws/agentcore-cdk';
import { CfnResource, Stack, Validations, type StackProps } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { execFileSync } from 'child_process';
import { cpSync, existsSync, readFileSync, rmSync, writeFileSync } from 'fs';
import { join, relative, sep } from 'path';
import { parseEnv } from 'util';

export interface AgentCoreStackProps extends StackProps {
  /** Props for the AgentCore application, produced by transformAgentCoreJson from agentcore/agentcore.json. */
  application: AgentCoreApplicationProps;
}

// The agent's settings that aren't secrets, from agentcore/.env.local beside the credentials'
// values, or else from the environment agentcore deploy runs in, so nobody's addresses are
// written into agentcore.json
const SETTINGS = ['UNDERCOVER_API', 'UNDERCOVER_GATEWAY_URL', 'UNDERCOVER_MEMORY_ID'];

/**
 * The stack the AgentCore CLI deploys. Everything declared in agentcore/agentcore.json is
 * created by the AgentCoreApplication construct.
 */
export class AgentCoreStack extends Stack {
  public readonly application: AgentCoreApplication;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);

    const root = props.application.projectRoot;
    const staged = stageCode(root);
    for (const runtime of props.application.spec.runtimes) {
      runtime.codeLocation = staged as typeof runtime.codeLocation;
    }

    this.application = new AgentCoreApplication(this, 'Application', props.application);
    useRuntimeV2(this);

    const localFile = join(root, 'agentcore', '.env.local');
    const local = existsSync(localFile) ? parseEnv(readFileSync(localFile, 'utf8')) : {};
    for (const runtime of props.application.spec.runtimes) {
      for (const name of SETTINGS) {
        const value = local[name] ?? process.env[name];
        if (value) {
          this.application.runtime(runtime.name).addEnvironmentVariable(name, value);
        }
      }
    }
  }
}

/**
 * Put every runtime in the stack on Runtime's platform version V2, which starts each new
 * session from a snapshot taken after the code's import. The CLI has no setting for it yet,
 * so this sets the CloudFormation property on the runtime the construct makes.
 */
function useRuntimeV2(stack: Stack): void {
  for (const child of stack.node.findAll()) {
    if (CfnResource.isCfnResource(child) && child.cfnResourceType === 'AWS::BedrockAgentCore::Runtime') {
      child.addPropertyOverride('PlatformVersion', 'V2');
      // The CDK's copy of CloudFormation's schema predates the property, and warns
      Validations.of(child).acknowledge({ id: 'CloudFormation-Validate::F3002', reason: 'The CDK predates PlatformVersion' });
    }
  }
}

/**
 * Stage the runtime's code for the zip build: the entry point from runtime/, the agent from
 * agent/ without its tests, and a pyproject.toml listing pyproject.toml's runtime group at
 * uv.lock's versions, since the build installs what a pyproject.toml lists and reads no lock.
 * The folder sits outside agentcore/.cache/<runtime>/, where the build installs the packages.
 */
function stageCode(root: string): string {
  const staged = join(root, 'agentcore', '.cache', 'source');
  rmSync(staged, { recursive: true, force: true });
  copyCode(join(root, 'runtime'), staged);
  copyCode(join(root, 'agent'), join(staged, 'agent'));
  const exported = execFileSync(
    'uv',
    ['export', '--only-group', 'runtime', '--no-hashes', '--no-emit-project', '--no-header', '--no-annotate'],
    { cwd: root, encoding: 'utf8' },
  );
  const packages = exported
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#'));
  const pyproject = [
    '[project]',
    'name = "undercover-agent"',
    'version = "0.1.0"',
    'requires-python = ">=3.12"',
    `dependencies = ${JSON.stringify(packages)}`,
    '',
  ];
  writeFileSync(join(staged, 'pyproject.toml'), pyproject.join('\n'));
  return staged;
}

/** Copy a folder of Python code, leaving out its tests and caches. */
function copyCode(from: string, to: string): void {
  cpSync(from, to, {
    recursive: true,
    filter: (path) => !relative(from, path).split(sep).some((part) => part === 'tests' || part === '__pycache__'),
  });
}
