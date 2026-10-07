# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 TU Wien & AWST
# SPDX-FileCopyrightText: For a full list of authors, see the AUTHORS file.

import os
import click
from importlib.metadata import version

from qa4sm_api.globals import (
    DEFAULT_INSTANCE, KNOWN_INSTANCES, QA4SM_DOTRC_PATH,
    _connect_with_credentials, _write_dotrc, _load_dotrc
)
from qa4sm_api.client_api import Connection


instance_option = click.option(
    "--instance", "-i",
    default=DEFAULT_INSTANCE,
    show_default=True,
    help=(
        "QA4SM instance to send trigger the validation run on. "
        f"Common values: {', '.join(KNOWN_INSTANCES)}"
    ),
)

@click.group(short_help="QA4SM API wrapper commands.")
@click.version_option(version=version("qa4sm_api"), prog_name="QA4SM Client API")
def cli():
    pass


@cli.group(short_help="API SETUP COMMANDS, see `qa4sm api --help`.")
def api():
    """
    API setup commands
    """
    pass


@cli.group(short_help="DOWNLOAD COMMANDS, see `qa4sm download --help`.")
def download():
    """
    Download data from QA4SM.
    """
    pass


@cli.group("list", short_help="LIST COMMANDS, see `qa4sm list --help`.")
def list_():
    """
    List information from QA4SM.
    """
    pass


def setup_api(instance=DEFAULT_INSTANCE):
    """
    Login to instance via username and password. Retrieve API token and store
    it in ~/.qa4smapirc for future use.
    """
    click.echo(f"Logging in to: {instance}")

    # Prompt for credentials (password input is hidden)
    username = click.prompt("Username")
    password = click.prompt("Password", hide_input=True)

    # Retrieve token from the remote instance
    try:
        cred_access = _connect_with_credentials(
            instance, username, password, False)
    except Exception as exc:
        raise click.ClickException(f"Login failed: {exc}") from exc

    if os.path.isfile(QA4SM_DOTRC_PATH):
        access = _load_dotrc(QA4SM_DOTRC_PATH)
        if instance not in access.keys():
            access[instance] = dict()
        access[instance]['token'] = cred_access[instance]['token']
        access[instance]['username'] = username
        action = "Added"
    else:
        access = dict()
        access[instance] = {'token': cred_access[instance]['token'],
                            'username': username}
        action = "Updated"

    _write_dotrc(access, QA4SM_DOTRC_PATH)

    click.echo(
        click.style(
            f"✓ {action} token for [{instance}] in {QA4SM_DOTRC_PATH}",
            fg="green",
        )
    )


@api.command("setup",
             short_help="Add token to `.qa4smapirc` file.")
@instance_option
def cli_setup(instance: str) -> None:
    """
    Authenticate with a QA4SM instance using your username and password
    to retrieve and store a token for the chosen instance )in ~/.qa4smapirc.
    """
    setup_api(instance)


@api.command("check",
             short_help="Check whether you can access an instance with "
                        "the stored token.")
@instance_option
def cli_check(instance: str) -> None:
    """
    Verify that your stored credentials allow access to a QA4SM instance.
    """
    qa4sm = Connection(instance, token='file', quiet_login=False)
    user = qa4sm.session.user
    if user is not None:
        click.echo(f"Success, you can now send API commands to {instance}!")
    else:
        click.echo("Failed! Please make sure you have configured your "
                   ".qa4smapirc file correctly.")

@list_.command(
    "runs",
    short_help="List your validation runs."
)
@instance_option
def cli_runs(instance: str) -> None:
    """
    List all validation runs of the user whose token is stored for the
    chosen instance.
    """
    qa4sm = Connection(instance, token='file')
    runs = qa4sm.my_validation_runs()

    if runs.empty:
        click.echo(f"No validation runs found on {instance}.")
        return

    runs['datasets'] = runs['datasets'].str.join("; ")
    runs['progress'] = runs['progress'].astype(str) + "%"
    runs = runs.reset_index()
    # Left-align all columns, similar to `column -t`
    widths = {col: max(len(col), runs[col].astype(str).str.len().max())
              for col in runs.columns}
    click.echo("  ".join(col.ljust(widths[col]) for col in runs.columns))
    for _, row in runs.iterrows():
        click.echo("  ".join(
            str(row[col]).ljust(widths[col]) for col in runs.columns))


@cli.command(
    "validate",
    short_help="Start a new validation run."
)
@click.argument(
    "CONFIG_FILE",
    type=click.File("r"),
)
@instance_option
def cli_validate(conf: str, instance: str) -> None:
    """
    Start a validation run on QA4SM using the settings from the passed
    configuration.

    \b
    Arguments:
      CONFIG_FILE  Path to the validation configuration to send. Hint: use the
      `qa4sm download config` command to download a template from an existing
      run.
    """
    # The above docstring is written to be displayed when calling --help
    qa4sm = Connection(instance, token='file')
    response = qa4sm.run_config_validation(conf, override=None)

    if not response.empty:
        run_id = response.name
        click.echo(f"Validation run started. See "
                   f"{qa4sm.session.base_url}ui/validation-result/{run_id}.")
    else:
        click.echo("No response received. No validation run started")


@download.command(
    "config",
    short_help="Download validation run configuration file."
)
@click.argument(
    "RUN_ID",
    type=click.STRING,
)
@click.option(
    "--out_path", "-o",
    default=None,
    metavar="PATH",
    help=(
        "Path where the downloaded config file is stored. If not specified, "
        "the current working directory is used. "
        "[default: current directory]"
    ),
)
@instance_option
def cli_download_conf(run_id: str, out_path: str, instance: str) -> None:
    """
    Download the configuration file of an existing online validation run.

    \b
    Arguments:
      RUN_ID  Validation run ID (UUID) to download. The ID is indicated, "
        "e.g., in the validation run URL."
    """
    # The above docstring is written to be displayed when calling --help
    out_path = out_path or os.getcwd()
    qa4sm = Connection(instance, token='file')
    conf = qa4sm.download_configuration(run_id, out_path)

    if conf.empty:
        print(f"Could not download configuration for run {run_id} from "
              f"{instance}. Make sure the run exists.")
    else:
        print(f"Configuration stored at "
              f"{os.path.join(out_path, f"{run_id}.json")}")


@download.command(
    "results",
    short_help="Download validation run results file."
)
@click.argument(
    "RUN_ID",
    type=click.STRING,
)
@click.option(
    "--out_path", "-o",
    default=None,
    metavar="PATH",
    help=(
        "Path where the downloaded results are stored. If not specified, "
        "the current working directory is used. "
        "[default: current directory]"
    ),
)
@instance_option
def cli_download_results(run_id: str, out_path: str, instance: str) -> None:
    """
    Download the configuration file of an existing online validation run.

    \b
    Arguments:
      RUN_ID  Validation run ID (UUID) to download. The ID is indicated
              in the validation run URL.
    """
    # The above docstring is written to be displayed when calling --help
    out_path = out_path or os.getcwd()
    qa4sm = Connection(instance, token='file')
    qa4sm.download_results(run_id, out_path, force_download=True)
