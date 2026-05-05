from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('audit', '0007_add_phase112_object_types'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='auditevent',
            name='audit_object_type_valid_chk',
        ),
        migrations.AddConstraint(
            model_name='auditevent',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    object_type__in=[
                        'organization',
                        'runbook',
                        'workflow',
                        'execution',
                        'execution_step',
                        'approval_request',
                        'approval_decision',
                        'policy',
                        'policy_rule',
                        'policy_evaluation',
                        'artifact',
                        'integration_connection',
                        'operation_profile',
                        'change_record',
                        'change_target',
                        'change_execution_binding',
                        'change_window',
                        'freeze_rule',
                        'target_lock',
                        'dispatch_eligibility_check',
                    ]
                ),
                name='audit_object_type_valid_chk',
            ),
        ),
    ]
