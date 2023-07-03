from constructs import Construct

from aws_cdk import (
    Stack,
    
    aws_codecommit as codecommit,
    aws_codebuild as codebuild,
    aws_ecs as ecs,
    aws_ecr as ecr,
    aws_codepipeline as codepipeline,
    aws_codepipeline_actions as codepipeline_actions,
    aws_ecs_patterns as ecs_patterns,
    aws_codedeploy as codedeploy,
    
    aws_iam as iam,
    aws_rds as rds,
    aws_ec2 as ec2,
    aws_ssm as ssm,
    aws_logs as lg
)

class TestStack2(Stack):
# class PipelineStack(core.Stack):

    def __init__(self, app: Construct, id: str, **kwargs) -> None:
        super().__init__(app, id, **kwargs)

        # CodeCommitリポジトリを作成
        repo = codecommit.Repository(
            self, 'Repository',
            # gitのリモートリポジトリの名前。
            repository_name='MyRepository2_222',
        )

        # ECRリポジトリを作成
        ecr_repo = ecr.Repository(
            self, 'ECRRepository',
            repository_name='my-ecr-repo',
        )

        # CodeBuildプロジェクトを作成
        # buildspecを設定し、dockerイメージをビルドしてECRにプッシュする
        build_project = codebuild.PipelineProject(
            self, 'Build',
            build_spec=codebuild.BuildSpec.from_object({
                'version': '0.2',
                'phases': {
                    'build': {
                        'commands': [
                            'echo Logging in to Amazon ECR...',
                            'aws --version',
                            '$(aws ecr get-login --region $AWS_DEFAULT_REGION --no-include-email)',
                            'docker build -t my-ecr-repo .',
                            'docker tag my-ecr-repo:latest $REPO_URL:latest',
                            'docker push $REPO_URL:latest',
                        ],
                    },
                    'post_build': {
                        'commands': [
                            # 「imagedefinitions.json」の作成によって、ECSにプッシュできる。
                            'printf \'[{\"name\":\"WebContainer\",\"imageUri\":\"%s\"}]\' $REPO_URL:latest > imagedefinitions.json'
                        ]
                    }
                },
                'env': {
                    'variables': {
                        'REPO_URL': ecr_repo.repository_uri,
                    },
                },
                'artifacts': {
                    # buildフェーズでの出力ファイルを記載しているみたい。
                    'files': ['imagedefinitions.json'],
                },
            }),
            environment=codebuild.BuildEnvironment(
                privileged=True,
            ),
        )

        # ECRリポジトリへのアクセス権をCodeBuildプロジェクトに付与
        ecr_repo.grant_pull_push(build_project.grant_principal)

        # VPCを定義。
        vpc = ec2.Vpc(self, "MyVpc", max_azs=2)
        
        # セキュリティグループを作成
        security_group = ec2.SecurityGroup(self, 'DatabaseSG',
            vpc=vpc,
            description='Allow sql access to RDS MySQL from any IP',
            allow_all_outbound=True  # Allow outbound traffic
        )
                
        # セキュリティグループにインバウンドルールを追加（全てのIPアドレスを許可）
        security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(3306),
            'Allow mysql access from any IP'
        )
        
        rds.DatabaseInstance(self, "MyRdsInstance",
            engine=rds.DatabaseInstanceEngine.mysql(
                version=rds.MysqlEngineVersion.VER_5_7_42
            ),
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.BURSTABLE3, ec2.InstanceSize.SMALL),
            vpc=vpc,
            
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),  # Choose public subnet
            security_groups=[security_group],  # Assign the security group
            publicly_accessible=True,  # Make the RDS instance publicly accessible
            
            database_name="db123", # ここでデータベース名を指定
        )

        # ECSを設定し、ECRからDockerイメージを取得するタスク定義を作成する
        # ECSクラスタを作成する
        cluster = ecs.Cluster(
            self, 'Cluster',
        )
        
        # 新しいiamロールを定義？
        task_execution_role = iam.Role(
            self, "TaskExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com")
        )
        # ecsがecrからプルするための権限みたい。
        task_execution_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonECSTaskExecutionRolePolicy")
        )
        
        # CloudWatch Logsへの書き込みを許可するIAMロールを作成
        task_execution_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchLogsFullAccess")
        )

        # ECSのログ設定
        log_group = lg.LogGroup(
            self, "LogGroup",
            log_group_name="your-log-group-name__0709",  # Specify your log group name
            retention=lg.RetentionDays.ONE_WEEK  # Specify your log retention policy
        )

        task_definition = ecs.FargateTaskDefinition(
            self, 'TaskDef',
            execution_role=task_execution_role
        )
        container = task_definition.add_container(
            "WebContainer",
            image=ecs.ContainerImage.from_registry("amazon/amazon-ecs-sample"),
            
            # CloudWatchLogsにログを出す。
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="your-stream-prefix__0709",  # Specify your stream prefix
                log_group=log_group  # Use the previously created log group
            ),
        )
        # ecsのポートマッピング。
        container.add_port_mappings(ecs.PortMapping(container_port=80))

        # ECSパターンの定義のおかげか、VPCは自動で設定もされるみたい。
        # （ただRDSと連携させるためには、定義してどのVPSを使用するか紐づけ要るみたい。）
        service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "Service",
            cluster=cluster,
            task_definition=task_definition,
            
            memory_limit_mib=512,
            cpu=256,
            public_load_balancer=True,
        )
    
        # ECSサービスの設定を更新するための権限をCodeBuildに付与
        build_project.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "ecs:DescribeServices",
                    "ecs:DescribeTaskDefinition",
                    "ecs:UpdateService",
                ],
                resources=["*"],
            )
        )

        # ソース変更を検出してパイプラインを実行するCodePipelineを作成する
        source_output = codepipeline.Artifact()
        build_output = codepipeline.Artifact()

        # パイプラインの定義
        pipeline = codepipeline.Pipeline(
            self, 'Pipeline',
            pipeline_name='MyPipeline',
            stages=[
                # CodeCommitフェーズの定義。
                codepipeline.StageProps(
                    stage_name='Source',
                    actions=[
                        codepipeline_actions.CodeCommitSourceAction(
                            action_name='CodeCommit_Source',
                            repository=repo,
                            output=source_output,
                        ),
                    ]
                ),
                # CodeBuildフェーズの定義。
                codepipeline.StageProps(
                    stage_name='Build',
                    actions=[
                        codepipeline_actions.CodeBuildAction(
                            action_name='CodeBuild',
                            project=build_project,
                            input=source_output,
                            outputs=[build_output],
                        ),
                    ]
                ),
                # CodeDeployフェーズの定義。
                # （実際にはECSがそういう動作をしているみたい？pipelineを結果を見ると「アクションプロバイダー」が「Amazon ECS」になってる。）
                codepipeline.StageProps(
                    stage_name='Deploy',
                    actions=[
                        codepipeline_actions.EcsDeployAction(
                            action_name='EcsDeployAction',
                            service=service.service,
                            image_file=build_output.at_path('imagedefinitions.json')
                        )
                    ]
                ),
            ],
        )
