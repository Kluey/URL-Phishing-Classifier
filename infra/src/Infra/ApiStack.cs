using Amazon.CDK;
using Amazon.CDK.AWS.Apigatewayv2;
using Amazon.CDK.AWS.Events;
using Amazon.CDK.AWS.Events.Targets;
using Amazon.CDK.AWS.Lambda;
using Amazon.CDK.AWS.Logs;
using Amazon.CDK.AwsApigatewayv2Integrations;
using Constructs;
using System.Collections.Generic;
using System.IO;
using EcrPlatform = Amazon.CDK.AWS.Ecr.Assets.Platform_;

namespace Infra
{
    public sealed class ApiStackProps : StackProps
    {
        /// <summary>Image to run; null builds api/Dockerfile from the repo root. Tests inject an ECR image.</summary>
        public DockerImageCode ImageCode { get; init; }

        /// <summary>Adds an EventBridge rule that calls /v1/health every 5 minutes (on in Program.cs unless -c warmup=false).</summary>
        public bool Warmup { get; init; }
    }

    /// <summary>The public API: HTTP API ($default route) → Lambda container running api.main.handler.</summary>
    public sealed class ApiStack : Stack
    {
        public const int MemoryMb = 3008;
        public const int ReservedConcurrency = 5;
        // The stage limits must not exceed what the function can run at once: a request that
        // passes the stage but finds no free instance is throttled by Lambda, and HTTP API
        // returns that as 503 instead of 429 (Day 7 burst test: 45 of 50 got 503 at burst 20).
        public const double RateLimit = 5;
        public const int BurstLimit = ReservedConcurrency;

        public ApiStack(Construct scope, string id, ApiStackProps props) : base(scope, id, props)
        {
            var logGroup = new LogGroup(this, "ClassifierLogs", new Amazon.CDK.AWS.Logs.LogGroupProps
            {
                Retention = RetentionDays.TWO_WEEKS,
                RemovalPolicy = RemovalPolicy.DESTROY,
            });

            var fn = new DockerImageFunction(this, "Classifier", new DockerImageFunctionProps
            {
                Code = props.ImageCode ?? RepoImage(),
                Architecture = Architecture.X86_64,
                MemorySize = MemoryMb,
                // HTTP API integrations time out at 30 s
                Timeout = Duration.Seconds(29),
                ReservedConcurrentExecutions = ReservedConcurrency,
                Environment = new Dictionary<string, string> { ["THRESHOLD"] = "0.8" },
                LogGroup = logGroup,
                Description = "GPT-2 hostname phishing classifier (FastAPI + Mangum)",
            });

            // $default route: FastAPI does the routing, so /docs works and unknown paths get its 404
            var api = new HttpApi(this, "Api", new HttpApiProps
            {
                ApiName = "phishing-check",
                DefaultIntegration = new HttpLambdaIntegration("ClassifierIntegration", fn),
            });

            var stage = (CfnStage)api.DefaultStage.Node.DefaultChild;
            stage.DefaultRouteSettings = new CfnStage.RouteSettingsProperty
            {
                ThrottlingRateLimit = RateLimit,
                ThrottlingBurstLimit = BurstLimit,
            };

            if (props.Warmup)
            {
                new Rule(this, "Warmup", new RuleProps
                {
                    Description = "Keeps one classifier instance warm",
                    Schedule = Schedule.Rate(Duration.Minutes(5)),
                    Targets = new IRuleTarget[]
                    {
                        new LambdaFunction(fn, new LambdaFunctionProps { Event = RuleTargetInput.FromObject(HealthEvent()) }),
                    },
                });
            }

            new CfnOutput(this, "ApiUrl", new CfnOutputProps { Value = api.ApiEndpoint });
            new CfnOutput(this, "FunctionName", new CfnOutputProps { Value = fn.FunctionName });
        }

        private static DockerImageCode RepoImage()
        {
            // cdk runs from infra/; the root .dockerignore keeps the context to api/, components/ and the weights
            var repoRoot = Path.GetFullPath(Path.Combine(Directory.GetCurrentDirectory(), ".."));
            return DockerImageCode.FromImageAsset(repoRoot, new AssetImageCodeProps
            {
                File = "api/Dockerfile",
                Platform = EcrPlatform.LINUX_AMD64,
            });
        }

        /// <summary>An HTTP API v2 event (same shape as api/events/health.json); Mangum rejects anything else.</summary>
        private static Dictionary<string, object> HealthEvent() => new()
        {
            ["version"] = "2.0",
            ["routeKey"] = "$default",
            ["rawPath"] = "/v1/health",
            ["rawQueryString"] = "",
            ["headers"] = new Dictionary<string, object> { ["host"] = "warmup" },
            ["requestContext"] = new Dictionary<string, object>
            {
                ["http"] = new Dictionary<string, object>
                {
                    ["method"] = "GET",
                    ["path"] = "/v1/health",
                    ["protocol"] = "HTTP/1.1",
                    ["sourceIp"] = "127.0.0.1",
                    ["userAgent"] = "eventbridge-warmup",
                },
                ["routeKey"] = "$default",
                ["stage"] = "$default",
            },
            ["isBase64Encoded"] = false,
        };
    }
}
