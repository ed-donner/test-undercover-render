import { AgentCoreApplication, type AgentCoreApplicationProps } from '@aws/agentcore-cdk';
import { CfnResource, Stack, Validations, type StackProps } from 'aws-cdk-lib';
import { Construct } from 'constructs';

export interface AgentCoreStackProps extends StackProps {
  /** Props for the AgentCore application, produced by transformAgentCoreJson from agentcore/agentcore.json. */
  application: AgentCoreApplicationProps;
}

/**
 * The stack the AgentCore CLI deploys. Everything declared in agentcore/agentcore.json is
 * created by the AgentCoreApplication construct. Add your own resources below it and wire
 * them to your runtimes and harnesses through the application's accessors.
 */
export class AgentCoreStack extends Stack {
  public readonly application: AgentCoreApplication;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);
    this.application = new AgentCoreApplication(this, 'Application', props.application);

    // Runtime's platform version V2 starts each new session from a snapshot taken after the
    // code's import. The CLI has no setting for it yet, so set it on the runtime's resource.
    for (const child of this.node.findAll()) {
      if (CfnResource.isCfnResource(child) && child.cfnResourceType === 'AWS::BedrockAgentCore::Runtime') {
        child.addPropertyOverride('PlatformVersion', 'V2');
        // The CDK's copy of CloudFormation's schema predates the property, and warns
        Validations.of(child).acknowledge({ id: 'CloudFormation-Validate::F3002', reason: 'The CDK predates PlatformVersion' });
      }
    }

    // Example: give a runtime a DynamoDB table.
    //
    // import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
    // const orders = new dynamodb.Table(this, 'Orders', {
    //   partitionKey: { name: 'pk', type: dynamodb.AttributeType.STRING },
    // });
    // const checkout = this.application.runtime('checkout'); // or .harness('support')
    // checkout.grantReadWrite(orders);
    // checkout.addEnvironmentVariable('ORDERS_TABLE', orders.tableName);
  }
}
