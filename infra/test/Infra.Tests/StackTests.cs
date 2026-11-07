using Amazon.CDK;
using Amazon.CDK.Assertions;
using Amazon.CDK.AWS.ECR;
using Amazon.CDK.AWS.Lambda;
using Infra;

namespace Infra.Tests;

public class ApiStackTests
{
    // An existing ECR image stands in for the Docker asset, so tests need neither Docker nor the weights
    private static Template Synth(bool warmup = false)
    {
        var app = new App();
        var images = new Stack(app, "Images");
        var repo = Repository.FromRepositoryArn(images, "Repo", "arn:aws:ecr:ap-southeast-2:123456789012:repository/test");
        var stack = new ApiStack(app, "PhishingApi", new ApiStackProps
        {
            ImageCode = DockerImageCode.FromEcr(repo),
            Warmup = warmup,
        });
        return Template.FromStack(stack);
    }

    private static Dictionary<string, object> Props(params (string Key, object Value)[] entries) =>
        entries.ToDictionary(e => e.Key, e => e.Value);

    [Fact]
    public void Function_has_expected_settings()
    {
        Synth().HasResourceProperties("AWS::Lambda::Function", Props(
            ("PackageType", "Image"),
            ("Architectures", new[] { "x86_64" }),
            ("MemorySize", 3008),
            ("Timeout", 29),
            ("ReservedConcurrentExecutions", 5),
            ("Environment", Props(("Variables", Props(("THRESHOLD", "0.8")))))));
    }

    [Fact]
    public void Logs_are_kept_two_weeks()
    {
        Synth().HasResourceProperties("AWS::Logs::LogGroup", Props(("RetentionInDays", 14)));
    }

    [Fact]
    public void Only_a_default_route_proxies_to_lambda()
    {
        var template = Synth();
        template.ResourceCountIs("AWS::ApiGatewayV2::Route", 1);
        template.HasResourceProperties("AWS::ApiGatewayV2::Route", Props(("RouteKey", "$default")));
        template.HasResourceProperties("AWS::ApiGatewayV2::Integration", Props(
            ("IntegrationType", "AWS_PROXY"),
            ("PayloadFormatVersion", "2.0")));
    }

    [Fact]
    public void Api_has_no_cors()
    {
        Synth().HasResourceProperties("AWS::ApiGatewayV2::Api", Props(("CorsConfiguration", Match.Absent())));
    }

    [Fact]
    public void Default_stage_is_throttled()
    {
        Synth().HasResourceProperties("AWS::ApiGatewayV2::Stage", Props(
            ("StageName", "$default"),
            ("DefaultRouteSettings", Props(("ThrottlingRateLimit", 10), ("ThrottlingBurstLimit", 20)))));
    }

    [Fact]
    public void Warmup_is_off_by_default()
    {
        Synth().ResourceCountIs("AWS::Events::Rule", 0);
    }

    [Fact]
    public void Warmup_sends_a_health_event_mangum_accepts()
    {
        var template = Synth(warmup: true);
        template.ResourceCountIs("AWS::Events::Rule", 1);
        template.HasResourceProperties("AWS::Events::Rule", Props(
            ("ScheduleExpression", "rate(5 minutes)"),
            ("Targets", Match.ArrayWith(new object[]
            {
                Match.ObjectLike(Props(("Input", Match.SerializedJson(Match.ObjectLike(Props(
                    ("version", "2.0"),
                    ("rawPath", "/v1/health"))))))),
            }))));
    }
}
