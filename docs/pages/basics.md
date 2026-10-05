# QA4SM Python Client API - Basic Overview

This is the Python client library for interacting with the [QA4SM](https://qa4sm.eu) web service for soil moisture validation. It provides programmatic access to discover datasets, run validation jobs, monitor their status, and download results.

## Installation

```bash
pip install qa4sm-api
```

## Prerequisites
Your account needs to be approved to use the API. Go to [https://qa4sm.eu/ui/user-profile](your profile page) 
and **Request a new API token**. 

Afterwards you need to store your token on your PCI in the file `~/.qa4smapirc`.
You can either do this manually or use the CLI tool as described below.

### Option 1: Automated Setup with CLI (Recommended)

Use the `qa4sm api setup` command to automatically create the configuration file:

```bash
qa4sm api setup
```

You will be prompted for your QA4SM credentials (username and password). The command will:
- Retrieve your API token from QA4SM.eu
- Create or update `~/.qa4smapirc` with your credentials
- Store your token securely for future use

### Option 2: Manual Configuration

Create the `~/.qa4smapirc` file manually with your credentials:

1. Obtain your API token from [your user profile page](https://qa4sm.eu/ui/user-profile)
2. Create or edit `~/.qa4smapirc` and add the following content:

```ini
[qa4sm.eu]
token: your_api_token_here
username: your_username
```

### Verifying Your Setup

To verify your authentication is working, you can run the following console
command

```bash
qa4sm api check
```

And it should print a success message if everything is configured correctly.

## Using the API

Once you've set up your authentication, you can use the API in your Python code.

### Initial Connection

At the start of your application, you need set up the connection to QA4SM. API commands
are then sent through this connection.

```python
from qa4sm_api.client_api import Connection

# Initialize connection (automatically uses token from ~/.qa4smapirc)
qa4sm = Connection()
```
## Connection - Core API Methods

The `Connection` class is the main interface to the QA4SM service.

### Dataset Discovery

```python
from qa4sm_api.client_api import Connection

# Initialize connection (uses token from ~/.qa4smapirc)
qa4sm = Connection()

# Get all available datasets (and their ID) as a DataFrame
datasets = qa4sm.datasets()

# Get versions for a specific dataset (by name or ID), e.g.
versions = qa4sm.versions("C3S_combined")
# or via the dataset ID
versions = qa4sm.versions(1)

# Get detailed metadata for a dataset
dataset_info = qa4sm.dataset_info(qa4sm.dataset_id("C3S_combined"))
# or via the ID
dataset_info = qa4sm.dataset_info(1)

# Get detailed metadata for a specific version

version_info = qa4sm.version_info(
    qa4sm.version_id("v202505", "C3S_combined"))
version_info = qa4sm.version_info(70)


# Get the time period for a version
start_date, end_date = qa4sm.get_period(70)
```

### Filter and Variable Information

```python
# Get details about a data filter
filter_info = qa4sm.filter_info(1)

# Get details about a dataset variable
variable_info = qa4sm.variable_info(1)
```

### Listing Your Validation Runs

```python
# Get all of your validation runs as a DataFrame, indexed by run ID, with
# the columns 'name', 'datasets' (list of dataset names) and 'progress' (0-100%)
runs = qa4sm.my_validation_runs()

# e.g. only show runs that are not finished yet
unfinished = runs[runs['progress'] < 100]
```

The same list is available from the command line:

```bash
qa4sm runs
```

### Validation Status Monitoring

```python
# Check if a validation run exists
exists = qa4sm.validation_exists("9aeb663b-e24e-4541-8331-6ec3e0318d1f")

# Get validation status and progress (0-100%)
status, progress = qa4sm.validation_status("9aeb663b-e24e-4541-8331-6ec3e0318d1f")
# Status can be: 'NOT FOUND', 'SCHEDULED', 'RUNNING', 'DONE', 'CANCELLED', 'ERROR'

# Get validation run timing
start_time, end_time = qa4sm.validation_time("9aeb663b-e24e-4541-8331-6ec3e0318d1f")

# Get validation duration (seconds and formatted string)
duration_seconds, duration_string = qa4sm.validation_duration("9aeb663b-e24e-4541-8331-6ec3e0318d1f")
```

## ValidationConfiguration

The `ValidationConfiguration` class manages validation job configurations.

```python
from qa4sm_api.client_api import ValidationConfiguration

# Load configuration from a JSON file
config = ValidationConfiguration.from_file("my_config.json")

# Download configuration from an existing validation run
config = ValidationConfiguration.from_remote(
    run_id="9aeb663b-e24e-4541-8331-6ec3e0318d1f",
    instance="qa4sm.eu",
    token="auto"
)

# Save configuration to a JSON file
config.dump("output_config.json")

# Access configuration values
name_tag = config['name_tag']
start_date = config['interval_from']
end_date = config['interval_to']
```

## Running Validations

Submit validation jobs for processing on the QA4SM server.

```python
# Method 1: Submit a ValidationConfiguration object
response = qa4sm.run_validation(config)
# The response is a pandas Series with the run_id as its name
run_id = response.name if not response.empty else None
if run_id:
    print("Validation run started with ID:", run_id)

# Method 2: Submit a configuration file path
response = qa4sm.run_config_validation("my_config.json")
# The response is a pandas Series with the run_id as its name
run_id = response.name if not response.empty else None

# Method 3: Submit with overrides
response = qa4sm.run_config_validation(
    "my_config.json",
    override={"name_tag": "my_custom_name"}
)
```

## Downloading Results

Retrieve validation outputs including graphics, NetCDF files, and statistics.

```python
# Download all results for a validation run
# This creates:
#   - <run_id>.nc (NetCDF data file)
#   - summary_stats.csv (summary statistics)
#   - qa4sm_graphics/ (directory with visualization files)
qa4sm.download_results(
    run_id="9aeb663b-e24e-4541-8331-6ec3e0318d1f",
    out_dir="/path/to/output",
    force_download=True
)

# Download only the configuration file
config = qa4sm.download_configuration(
    run_id="9aeb663b-e24e-4541-8331-6ec3e0318d1f",
    out_dir="/path/to/output"
)
```

## Delete Validation Run

Remove one of **your** online validation runs via its ID.

```python
# Remove a previously run online validation (that you own). This means that
#   - the run and all the results are removed
#   - the validation URL is not accessible anymore
#   - results are not available for download anymore
qa4sm.delete(run_id="9aeb663b-e24e-4541-8331-6ec3e0318d1f")
```


## Quick Start Example

Complete workflow from discovery to results:

```python
from qa4sm_api.client_api import Connection, ValidationConfiguration
import time

# Initialize connection (uses token from ~/.qa4smapirc)
qa4sm = Connection()

# Discover available datasets
datasets = qa4sm.datasets()
print(datasets[['short_name', 'pretty_name']])

# Get versions for a dataset
versions = qa4sm.versions("C3S_combined")
print(versions[['short_name', 'pretty_name', 'time_range_start', 'time_range_end']])

# Load or create a validation configuration
config = ValidationConfiguration.from_file("validation_config.json")

# Submit validation job
response = qa4sm.run_validation(config)
# The response is a pandas Series with the run_id as its name
run_id = response.name if not response.empty else None
if run_id:
    print(f"Validation started: {run_id}")

# Monitor progress
while True:
    status, progress = qa4sm.validation_status(run_id)
    print(f"Status: {status}, Progress: {progress}%")

    if status == 'DONE':
        print("Validation completed successfully!")
        break
    elif status in ['ERROR', 'CANCELLED', 'NOT FOUND']:
        print(f"Validation failed: {status}")
        break
    else:
        time.sleep(30)

# Download results
qa4sm.download_results(run_id, out_dir="./my_results")
print(f"Results downloaded to ./my_results/{run_id}.nc")

# Finally, delete the validation run again
qa4sm.delete(run_id)
```

## Error Handling

Common exceptions you may encounter:

```python
from qa4sm_api.globals import ValidationRunNotFoundError, ValidationInstanceError

try:
    status = qa4sm.validation_status("invalid-run-id")
except ValidationRunNotFoundError:
    print("Validation run not found")

try:
    connection = Connection(instance="unknown-instance", token="auto")
except ValidationInstanceError:
    print("Unknown validation instance")
```