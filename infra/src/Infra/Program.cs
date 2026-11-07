using Amazon.CDK;

namespace Infra
{
    sealed class Program
    {
        public static void Main(string[] args)
        {
            var app = new App();
            var env = new Environment
            {
                Account = System.Environment.GetEnvironmentVariable("CDK_DEFAULT_ACCOUNT"),
                Region = System.Environment.GetEnvironmentVariable("CDK_DEFAULT_REGION"),
            };

            // The GitHub OIDC provider and the github-actions-deploy role are created by hand: an
            // organization SCP denies OIDC provider actions to CloudFormation (see docs/plan.md)
            new ApiStack(app, "PhishingApi", new ApiStackProps
            {
                Env = env,
                // Cold instances often miss Lambda's init limits, so keep one warm; -c warmup=false turns it off
                // Case-insensitive: a JSON boolean in cdk.json arrives as a .NET bool, whose ToString() is "False"
                Warmup = !string.Equals(app.Node.TryGetContext("warmup")?.ToString(), "false", System.StringComparison.OrdinalIgnoreCase),
            });

            Tags.Of(app).Add("project", "url-phishing-classifier");
            app.Synth();
        }
    }
}
