from django.db import migrations


MYSQL_FORWARD_SQL = (
    """
    ALTER TABLE core_nftasset
      ADD COLUMN bc_source_project_unique varchar(128)
        GENERATED ALWAYS AS (NULLIF(source_project_id, '')) STORED,
      ADD UNIQUE INDEX bc_uq_owner_source_project
        (owner_id, bc_source_project_unique)
    """,
    """
    ALTER TABLE core_modelasset
      ADD COLUMN bc_source_model_unique varchar(160)
        GENERATED ALWAYS AS (NULLIF(source_model_id, '')) STORED,
      ADD UNIQUE INDEX bc_uq_seller_model_version
        (seller_id, bc_source_model_unique, version)
    """,
    """
    ALTER TABLE core_modelpurchase
      ADD COLUMN bc_paid_buyer_unique bigint
        GENERATED ALWAYS AS (
          CASE WHEN status = 'paid' THEN buyer_id ELSE NULL END
        ) STORED,
      ADD UNIQUE INDEX bc_uq_paid_model_buyer
        (model_id, bc_paid_buyer_unique)
    """,
)

MYSQL_REVERSE_SQL = (
    "ALTER TABLE core_modelpurchase DROP INDEX bc_uq_paid_model_buyer, DROP COLUMN bc_paid_buyer_unique",
    "ALTER TABLE core_modelasset DROP INDEX bc_uq_seller_model_version, DROP COLUMN bc_source_model_unique",
    "ALTER TABLE core_nftasset DROP INDEX bc_uq_owner_source_project, DROP COLUMN bc_source_project_unique",
)


def add_mysql_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    with schema_editor.connection.cursor() as cursor:
        for statement in MYSQL_FORWARD_SQL:
            cursor.execute(statement)


def remove_mysql_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    with schema_editor.connection.cursor() as cursor:
        for statement in MYSQL_REVERSE_SQL:
            cursor.execute(statement)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("core", "0002_model_marketplace"),
    ]

    operations = [
        migrations.RunPython(add_mysql_guards, remove_mysql_guards),
    ]
