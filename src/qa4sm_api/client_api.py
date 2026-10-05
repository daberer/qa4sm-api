# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 TU Wien & AWST
# SPDX-FileCopyrightText: For a full list of authors, see the AUTHORS file.

import json
import warnings
import requests
import time
import pandas as pd
from typing import Union, Optional, List
import os
import zipfile
from pathlib import Path
from datetime import datetime
import pprint as pprint

from qa4sm_api.globals import (QA4SM_DOTRC_PATH, ValidationRunNotFoundError,
                               AuthenticationError, ValidationInstanceError,
                               _load_dotrc, make_dummy_ok_response,
                               Qa4smEnvironmentError)


class Response:

    def __init__(self, response, serialize=True):
        self.response = response
        if serialize:
            self.response = self.response.json()

    @property
    def data(self) -> List[dict]:
        if self.response is None:
            raise ValueError("No response data is available")
        elif isinstance(self.response, dict):
            response = [self.response]
        else:
            response = self.response

        return response

    @property
    def pandas(self) -> Union[pd.DataFrame, pd.Series]:
        """ Get all request return data as a DataFrame """
        df = pd.DataFrame.from_dict(self.data, orient='columns') \
                           .set_index('id') \
                           .sort_index()
        if len(df.index) == 1:
            return df.iloc[0, :]  # dtype: pd.Series
        else:
            return df  # dtype: pd.DataFrame


class Access:

    def __init__(self, access):
        """
        Initialize the Access class with credentials to the API.
        """
        self.access = access

    def __repr__(self):
        try:
            instances = list(self.access.keys())
            n = len(instances)
        except TypeError:
            instances = []
            n = 0
        return f"{n} QA4SM Instances: {instances}"

    def __getitem__(self, item):
        return self.access[item]

    @classmethod
    def from_available(cls):
        # Try first if the environment variables are set
        try:
            return cls.from_env()
        except Qa4smEnvironmentError:
            return cls.from_dotrcfile()

    @classmethod
    def from_env(cls):
        try:
            instance = os.environ["QA4SM_INSTANCE"]
        except KeyError:
            raise Qa4smEnvironmentError(
                "QA4SM_INSTANCE not found in environment variables.")
        try:
            token = os.environ["QA4SM_TOKEN"]
        except KeyError:
            raise Qa4smEnvironmentError(
                "QA4SM_TOKEN not found in environment variables.")
        access = {instance: {"token": token}}

        return cls(access)

    @classmethod
    def from_dotrcfile(cls, path=QA4SM_DOTRC_PATH):
        """
        Load access from dotrc file.

        Parameters
        ----------
        path: str
            Path to the dotrc file
        """
        config = _load_dotrc(path)
        return cls(config)

    @classmethod
    def with_token(cls, instance, token):
        """
        Load access with token for a specific instance.

        Parameters
        ----------
        instance: str
            QA4SM instance name
        token: str
            API token for the instance

        Returns
        -------
        Access
            Access object with token
        """
        return cls({instance: {'token': token}})

    @classmethod
    def without_token(cls, instance):
        """
        Create access for instance without token (limited access).

        Parameters
        ----------
        instance: str
            QA4SM instance name

        Returns
        -------
        Access
            Access object with None token (limited access)
        """
        warnings.warn(f"No token was found for {instance}, "
                      f"continue as anonymous "
                      f"user (with limited access)")
        return cls({instance: {'token': None}})


class Session:
    """
    Wrapper to send API request to QA4SM after authentication.
    """
    _max_retries = 10  # for all requests
    _wait_retry_s = 0.1  # seconds between requests

    def __init__(self,
                 instance="qa4sm.eu",
                 token="auto",
                 protocol="https",
                 quiet_login=True):
        """
        Session to send requests to QA4SM via API.

        Parameters
        ----------
        instance: str, optional (default: 'qa4sm.eu')
            Base URL to send API requests to
        token: str, optional (default: None)
            To authenticate with QA4SM API pass your token.
            While some request work without authentication, all
            user-specific request need you to log in first.
            - "auto" (default) will try "file" first and continue with "none" otherwise.
            - "file" uses the token from the ~/.qa4smapirc file (error if not found).
            - "none" to force not setting a token even if .qa4smapirc is found.
            - "<token>" pass a valid token to use it directly (without checking .qa4smapirc)
        protocol: Literal['http', 'https'], optional (default: 'https')
            Developer setting. Use https for the public instances (test, prod)
            or http for local instances.
            e.g., 127.0.0.1:8000
        quiet_login: bool, optional
            Don't print welcome message on login.
        """
        self.headers = {"Content-Type": "application/json"}
        self.instance = instance
        self.base_url = f"{protocol}://{self.instance}/"
        self.api_url = self.base_url + "api/"
        self.quiet_login = quiet_login

        self.client = requests.Session()
        self.response = None

        if token == "auto":
            try:
                self.access = Access.from_available()
            except FileNotFoundError as e:
                warnings.warn(f"{str(e)}. Continue as ANONYMOUS user.")
                self.access = Access.without_token(self.instance)
        elif token == "file":
            self.access = Access.from_dotrcfile()
        elif token is None or token.lower() == "none":
            self.access = Access.without_token(self.instance)
        elif isinstance(token, str):
            self.access = Access.with_token(self.instance, token)
        else:
            raise NotImplementedError("token must be one of "
                                      "['auto', 'file', 'none', or <TOKEN>]")

        self.user = "ANONYMOUS"
        if instance not in list(self.access.access.keys()):
            raise ValidationInstanceError(
                f"Unknown instance {instance}. "
                f"Please add it to your .qa4smapirc file.")
        else:
            token = self.access[instance]['token']
        if token is not None:
            _ = self.login_with_token(token)
        else:
            warnings.warn("No token was passed, limited API access. "
                          "Only public API calls are possible.")

    def __repr__(self):
        return f"{self.user}@{self.instance}"

    def url(self, *args) -> str:
        # Join URL parts
        args = [str(a) for a in args]
        url = '/'.join(args).replace('//', '/')

        return self.api_url + url

    def login_with_token(self, token) -> int:
        """
        status_code
        200: OK, login successful
        """
        self.headers["Authorization"] = f"Token {token}"
        re = self.get(self.url("auth/login"), headers=self.headers)
        username = re.pandas['username']
        if not self.quiet_login:
            print(f"Hi, {username}! You're successfully logged "
                  f"in at {self.api_url}!")
        self.user = username
        self.access = Access(
            {self.instance: {
                'token': token,
                'username': self.user
            }})
        return 200

    def login_with_credentials(self, username=None, password=None):
        """
        Authenticate with username and password to receive a token for
        subsequent requests.

        Parameters
        ----------
        username: str
            Username for the chosen QA4SM instance.
        password: str
            Password for the chosen QA4SM instance.
        quiet: bool, optional (default: False)
            Suppress welcome message.

        Returns
        -------
        token: str
            user login token
        """
        data = {'username': username, 'password': password}
        try:
            response = self.post(self.url("auth/login"), data=data)
        except requests.exceptions.HTTPError as _:
            raise AuthenticationError(
                f"Login failed for {username} with the passed "
                f"credentials. Please make sure that the chosen "
                f"username/password combination is valid for "
                f"{self.instance}.")
        token = response.pandas['auth_token']
        if token is None:
            raise AuthenticationError(
                f"User does not have a "
                f"token yet. Please request one first at "
                f"https://qa4sm.eu/ui/user-profile.")
        self.login_with_token(token)
        return token

    def delete(self, url, serialize=True, dry_run=False, **kwargs):
        """
        Send a DELETE request to the API. Retry on fail.

        Parameters
        ----------
        url: str
            URL to send the request to
        serialize: bool, optional
            Whether the response should be json serialized
        dry_run: bool, optional
            Don't perform the actual deletion. Return dummy response.
        kwargs:
            Additional kwargs are passed to requests.delete

        Returns
        -------
        Response
            Response from the API
        """
        if self.headers is None:
            raise ValueError("No headers found to post request.")

        for attempt in range(self._max_retries):
            try:
                if dry_run:
                    response = make_dummy_ok_response()
                else:
                    response = requests.delete(
                        url, headers=self.headers, timeout=10, **kwargs)

                response.raise_for_status()
                response = Response(response, serialize=serialize)
                self.response = response
                return response
            except requests.exceptions.RequestException as e:
                if attempt == self._max_retries - 1:  # Last attempt
                    raise e
                time.sleep(self._wait_retry_s)

    def post(self, url, data, serialize=True, **kwargs) -> Response:
        """
        Send a POST request to the API.

        Parameters
        ----------
        url: str
            URL to send the request to
        data: dict
            Data to include in the request body
        serialize: bool, optional
            Whether the response should be json serialized
        kwargs:
            Additional kwargs are passed to requests.delete

        Returns
        -------
        Response
            Response from the API
        """
        if self.headers is None:
            raise ValueError("No headers found to post request.")

        for attempt in range(self._max_retries):
            try:
                response = requests.post(
                    url, headers=self.headers, json=data, timeout=10, **kwargs)
                response.raise_for_status()
                response = Response(response, serialize=serialize)
                self.response = response
                return response
            except requests.exceptions.RequestException as e:
                if attempt == self._max_retries - 1:  # Last attempt
                    raise e
                time.sleep(self._wait_retry_s)

    def get(self, url, serialize=True, **kwargs) -> Response:
        """
        Send a GET request to the API.

        Parameters
        ----------
        url: str
            URL to send the request to
        serialize: bool, optional
            Whether the response should be json serialized
        kwargs:
            Additional kwargs are passed to requests.delete

        Returns
        -------
        Response
            Response from the API
        """
        for attempt in range(self._max_retries):
            try:
                response = requests.get(url, timeout=10, **kwargs)
                response.raise_for_status()
                response = Response(response, serialize=serialize)
                self.response = response
                return response

            except requests.exceptions.RequestException as e:
                if attempt == self._max_retries - 1:  # Last attempt
                    raise e

                time.sleep(self._wait_retry_s)


class ValidationConfiguration:

    def __init__(self, config_data: dict):
        self.data = config_data[0] if len(config_data) == 1 else config_data

    def __repr__(self):
        return f"{self.__class__.__name__}(data={pprint.pformat(self.data)})"

    def __getitem__(self, item):
        return self.data[item]

    def __setitem__(self, key, value):
        if key not in self.data.keys():
            raise KeyError(f"{key} is not in the configuration.")
        self.data[key] = value

    def __eq__(self, other):
        return self.data == other.data

    @property
    def empty(self):
        return len(self.data) == 0

    def dump(self, path):
        """
        Dump the configuration to a new json file.

        Parameters
        ----------
        path: str or Path
            Path to json file to create
        """
        with open(Path(path), 'w') as jfile:
            json.dump(self.data, jfile, indent=2)

    @classmethod
    def from_remote(cls, run_id, **connection_kwargs):
        """
        Load a configuration from an existing remote run. Configs are
        public, so it's not necessary to authenticate.

        Parameters
        ----------
        run_id: str
            UID of the validation run at the chosen instance
            (see connection_kwargs).
        instance: str, optional (default: "qa4sm.eu")
            see qa4sm_api.client_api.Connection
        token: str, optional
            see qa4sm_api.client_api.Connection
        protocol: str, optional
            see qa4sm_api.client_api.Connection
        """
        connection = Connection(**connection_kwargs)
        config = connection.download_configuration(run_id=run_id)
        return cls(config_data=config.data)

    @classmethod
    def from_file(cls, path):
        """
        Load a configuration from a json file.

        Parameters
        ----------
        path: str or Path
            Path to the json file to load
        """
        with open(Path(path), 'r', encoding='utf-8') as file:
            data = json.load(file)

        return cls(data)


class Connection:
    """
    Communication with QA4SM.
    """

    def __init__(self,
                 instance: str = "qa4sm.eu",
                 token="auto",
                 protocol="https",
                 quiet_login=True):
        """
        Parameters
        ----------
        instance: str, optional (default: "qa4sm.eu")
            service URL or IP:PORT, e.g
            - qa4sm.eu [productive]
            - test.qa4sm.eu [test]
            - test2.qa4sm.eu [test2]
            - 0.0.0.0:8000 [develop]
        token: str, optional
            Authentication user token (required to POST)
            - "auto" (default) will try "file" first and continue with "none"
              otherwise.
            - "file" will search for a token in a .qa4smapirc file
            - "none" will force not using a token (only public commands)
            - "<token>" will use the passed token directly
        protocol: str, optional
            Developer setting. Use https for the public instances (test, prod)
            or http for local instances.
            e.g., 127.0.0.1:8000
        quiet_login: bool, optional
            Don't print welcome message on login.
        """
        self.session = Session(instance, token, protocol, quiet_login)

    def __repr__(self):
        s = f"{type(self).__module__}.{type(self).__qualname__}"
        return f"{s}(session={self.session})"

    def _verify_connection(self):
        self.user()

    def url(self, *args, **kwargs) -> str:
        return self.session.url(*args, **kwargs)

    def login(self, username, password):
        self.session.login_with_credentials(username, password)

    def user(self) -> pd.Series:
        re = self.session.get(
            self.url("auth/login"), headers=self.session.headers)
        return re.pandas

    def _find(self, df, val):
        """
        In the passed dataframe, find the rows (ids) that contain val.
        Will throw an error if the value is not found or if multiple
        are found.

        Parameters
        ----------
        df: pd.DataFrame
            Pandas Dataframe to search
        val: Any
            Value to find

        Returns
        -------
        id: int
        """
        idx = df[df.eq(val).any(axis=1)].index.tolist()
        if len(idx) == 0:
            raise ValueError(f"{val} was not found. "
                             f"Please pass a valid name or ID.")
        elif len(idx) > 1:
            raise ValueError(f"Multiple instances for {val} found. "
                             f"Please pass a unique name or ID.")
        else:
            idx = idx[0]

        return int(idx)

    def dataset_id(self, dataset: str) -> int:
        """
        Get dataset ID from short name.

        Parameters
        ----------
        dataset: str
            Dataset short name

        Returns
        -------
        id: int
            Dataset ID
        """
        datasets = self.datasets()[['short_name', 'pretty_name']]
        return self._find(datasets, dataset)

    def version_id(self, version, dataset):
        """
        Get the version ID for a passed version name

        Parameters
        ----------
        version: str
            Version name
        dataset: str or int
            Dataset id or short name

        Returns
        -------
        version_id: int
            Version ID
        """
        versions = self.versions(dataset)[['short_name', 'pretty_name']]
        return self._find(versions, version)

    def datasets(self) -> pd.DataFrame:
        """
        Get a list of available datasets.
        """
        r = self.session.get(self.url("dataset"))
        df = r.pandas
        return df

    def versions(self, ds) -> pd.DataFrame:
        """
        Get the version information for a dataset.

        Parameters
        ----------
        ds: int or str
            The dataset index or short name to get versions for

        Returns
        -------
        df: pd.DataFrame
            Version information for the chosen dataset
        """
        ds_id = self.dataset_id(ds) if isinstance(ds, str) else ds

        datasets = self.datasets()
        version_ids = datasets.loc[ds_id, 'versions']

        dfs = []
        for vid in version_ids:
            r = self.session.get(self.url("dataset-version", vid))
            row = r.pandas.T.to_frame().T
            dfs.append(row)

        return pd.concat(dfs, axis=0).sort_index()

    def dataset_info(self, dataset: Union[str, int]) -> pd.Series:
        """
        Get dataset metadata

        Parameters
        ----------
        dataset: str or int
            Dataset name or ID

        Returns
        -------
        ser: pd.Series
        """
        if isinstance(dataset, str):
            ds_id = self.dataset_id(dataset)
        else:
            ds_id = dataset
        ser = self.datasets().loc[ds_id]
        ser['id'] = ds_id
        return ser

    def version_info(self,
                     version: Union[str, int],
                     dataset: Optional[Union[str, int]] = None) -> pd.Series:
        """
        Get version metadata

        Parameters
        ----------
        version: str or int
            Version name or ID.
        dataset: str or int
            Dataset name or ID that the version belongs to.
            Only required when version is a string

        Returns
        -------
        ser: pd.Series
        """
        if isinstance(version, str):
            vers_id = self.version_id(version, dataset)
        else:
            vers_id = version
        re = self.session.get(self.url("dataset-version", vers_id))
        ser = re.pandas
        ser['id'] = vers_id
        return ser

    def variable_info(self, var_id) -> pd.Series:
        """
        Get information about a dataset variable.

        Parameters
        ----------
        var_id: int
            The ID of the dataset variable to get information for

        Returns
        -------
        ds: pd.Series
            Information about the dataset variable
        """
        re = self.session.get(self.url("dataset-variable", var_id))
        ds = re.pandas
        ds['id'] = var_id
        return ds

    def filter_info(self, filter_id):
        """
        Get information about a data filter.

        Parameters
        ----------
        filter_id: int
            The ID of the data filter to get information for

        Returns
        -------
        ds: pd.Series
            Information about the data filter
        """
        re = self.session.get(self.url("data-filter"))
        ds = re.pandas
        ds = ds.loc[filter_id, :]
        ds['id'] = filter_id
        return ds

    def get_period(self, vers_id: int) -> (str, str):
        """
        Get start and end date of selected dataset directly from the service
        """
        ds = self.version_info(vers_id)
        return ds["time_range_start"], ds["time_range_end"]

    def check_errors(self, validation_id):
        """Check if the passed validation run has ended with an error"""
        # TODO: Should be implemented in API
        raise NotImplementedError()

    def _remote_val_status(self, validation_id):
        url = self.url(f"validation-runs-status/{validation_id}")
        response = self.session.get(url, headers=self.session.headers).data[0]
        return response

    def _remote_timing(self, validation_id):
        url = self.url(f"validation-runs-timing/{validation_id}")
        response = self.session.get(url, headers=self.session.headers).data[0]
        return response

    def validation_exists(self, validation_id: str) -> bool:
        """
        Check if a validation run exists online (running or finished, not
        deleted).
        """
        try:
            _ = self._remote_val_status(validation_id)
        except requests.exceptions.HTTPError:
            return False
        return True

    def validation_time(self, validation_id: str) -> \
            (Union[datetime, None], Union[datetime, None]):
        """
        Get start and end time when a validation run was processing.
        This works for finished OR running validations.

        Returns
        -------
        start_time: datetime or None
            None means that the validation was not started
        """
        if not self.validation_exists(validation_id):
            raise ValidationRunNotFoundError(validation_id)
        else:
            response = self._remote_timing(validation_id)
            start_time = pd.to_datetime(response["start_time"]).to_pydatetime()
            end_time = response["end_time"]
            if end_time is not None:
                end_time = pd.to_datetime(end_time).to_pydatetime()

            return start_time, end_time

    def validation_duration(self, validation_id: str) -> (int, str):
        """
        Get the duration of a validation run in seconds and formatted string.
        This works for finished OR running validations
        """
        if not self.validation_exists(validation_id):
            raise ValidationRunNotFoundError(validation_id)
        else:
            url = self.url(f"validation-runs-timing/{validation_id}")
            response = self.session.get(
                url, headers=self.session.headers).data[0]

            duration_seconds = response["duration_seconds"]
            duration_format = response["duration_format"]

            return duration_seconds, duration_format

    def validation_status(self, validation_id):
        """
        Check if the passed validation run is still running, completed or
        is not found.

        Parameters
        ----------
        validation_id: str
            Hash of the remote validation run to check.

        Returns
        -------
        status: str
           Status of the validation run. Can be one of:
            - 'NOT FOUND': The validation id was not found
            - 'SCHEDULED': The validation is queued
            - 'RUNNING': The validation is still running
            - 'DONE': The validation is completed
            - 'CANCELLED': The validation was cancelled
            - 'ERROR': The validation failed with an error
        progress: int
            Progress of the validation run in percent (0-100).
        """
        exists = self.validation_exists(validation_id)

        if not exists:
            return "NOT FOUND", 0
        else:
            response = self._remote_val_status(validation_id)
            status = response['status']
            progress = response['progress']
            return status, progress

    def my_validation_runs(self) -> pd.DataFrame:
        """
        List all validation runs of the logged-in user.

        Returns
        -------
        runs: pd.DataFrame
            One row per validation run, indexed by run id, with the
            columns 'name', 'datasets' (list of dataset names) and
            'progress' (in percent, 0-100).
        """
        url = self.url("my-validation-runs-with-token")
        response = self.session.get(url, headers=self.session.headers)
        runs = response.data[0]["validation_runs"]
        return pd.DataFrame(
            runs, columns=["id", "name", "datasets", "progress"]) \
            .set_index("id")

    def run_validation(self, config):
        """
        Trigger validation run based on the passed config.

        Parameters
        ----------
        config: ValidationConfiguration
            Validation configuration to send to the service

        Returns
        -------
        response: pd.Series
            Response from validation run
        """
        re = self.session.post(self.url("start-validation"), data=config.data)

        return re.pandas

    def download_configuration(self, run_id, out_dir=None):
        """
        Download validation configuration used for a specific run.

        Parameters
        ----------
        run_id: str
            UID of remote run to download configuration for
        out_dir: str, optional
            To save the config as a .json file, pass the storage path

        Returns
        -------
        config: ValidationConfiguration
            Downloaded Configuration object
        """
        url = self.url(f"validation-configuration/{run_id}")
        response = self.session.get(url)
        config = ValidationConfiguration(response.data)
        if out_dir is not None:
            config.dump(os.path.join(out_dir, f"{run_id}.json"))
        return config

    def delete(self, run_id, dry_run=False):
        """
        Completely delete an online validation run. This means that the results
        cannot be accessed anymore afterwards.

        Parameters
        ----------
        run_id: str
            UID of remote run to download results for
        dry_run: bool, optional
            Don't perform the actual deletion. Return dummy response.

        Returns
        -------
        response: Response
            Response from server. Dummy OK response for dry_run=True.
        """
        url = self.url(f"delete-validation/{run_id}/")
        response = self.session.delete(url, serialize=False, dry_run=dry_run)
        return response

    def download_results(self, run_id, out_dir, force_download=False):
        """
        Download all results for a run

        Parameters
        ----------
        run_id: str
            UID of remote run to download results for
        out_dir: str or Path
            Where the results are stored, will be created if it doesn't exist
            yet.
        force_download: bool, optional
            Always download, replace any existing local files.
            If False, only downloads results that don't exist locally.
        """
        out_dir = Path(out_dir)

        params = {
            "validationId": run_id,
            "fileType": "graphics",
        }

        os.makedirs(out_dir, exist_ok=True)

        graphx_dir = os.path.join(out_dir, "qa4sm_graphics")
        if force_download or (not os.path.exists(graphx_dir)):
            re = self.session.get(
                self.url("download-result"),
                serialize=False,
                params=params,
                stream=True)
            file_out = os.path.join(out_dir, "graphics.zip")
            with open(file_out, "wb") as file:
                for chunk in re.response.iter_content(chunk_size=8192):
                    file.write(chunk)

            with zipfile.ZipFile(file_out, 'r') as zip_ref:
                zip_ref.extractall(graphx_dir)
            # Remove .zip after extraction
            os.remove(file_out)

        params["fileType"] = "netCDF"
        file_out = os.path.join(out_dir, f"{run_id}.nc")
        if force_download or (not os.path.exists(file_out)):
            re = self.session.get(
                self.url("download-result"),
                serialize=False,
                params=params,
                stream=True)
            with open(file_out, "wb") as file:
                for chunk in re.response.iter_content(chunk_size=8192):
                    file.write(chunk)

        _ = params.pop("fileType")
        file_out = os.path.join(out_dir, f"summary_stats.csv")
        if force_download or (not os.path.exists(file_out)):
            re = self.session.get(
                self.url("download-statistics-csv"),
                serialize=False,
                params=params,
                stream=True)
            with open(file_out, "wb") as file:
                for chunk in re.response.iter_content(chunk_size=8192):
                    file.write(chunk)

    def run_config_validation(self, config_path, override=None):
        """
        Trigger validation run based on the passed config.

        Parameters
        ----------
        config_path: str
            Path to the config json to post.
        override: dict, optional (default: None)
            keys and values to override settings in the configuration.

        Returns
        -------
        response: dict
            Response from validation run (or config if dry_run is True)
        """
        config = ValidationConfiguration.from_file(config_path)

        if override is not None:
            for k, v in override.items():
                if k not in config.data:
                    raise KeyError(f"{k} does not exist in config.")
                else:
                    config.data[k] = v

        response = self.run_validation(config)

        return response
