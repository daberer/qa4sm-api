import os

import tempfile
import unittest
from pathlib import Path
import pandas as pd
import pytest
from unittest.mock import Mock, patch
import requests
from qa4sm_api.client_api import Connection, Session, Response, ValidationConfiguration, ValidationInstanceError
from qa4sm_api.globals import ValidationRunNotFoundError, AuthenticationError, _write_dotrc, _load_dotrc
from qa4sm_api.client_api import Access

try:
    QA4SM_ACCESS = Access.from_available().access
except:
    QA4SM_ACCESS = None


class TestResponse(unittest.TestCase):
    re = [{'username': 'testuser', 'email': 'test.user@test.com',
           'first_name': 'Test', 'last_name': 'User',
           'organisation': 'asd', 'last_login': '2026-03-10T17:28:22.995415Z',
           'date_joined': '2020-07-17T13:11:25Z',
           'country': 'AT', 'orcid': '', 'id': 999, 'copied_runs': [],
           'space_limit': 'unlimited', 'space_limit_value': None,
           'space_left': None, 'is_staff': True, 'is_superuser': True,
           'auth_token': 'ab123'}]

    def setUp(self):
        self.re = Response(self.re, serialize=False)

    def test_data(self):
        data = self.re.data
        assert len(data) == 1
        data = data[0]
        assert data['space_left'] is None
        assert data['username'] == 'testuser'
        assert data['is_staff'] == True

    def test_pandas(self):
        data = self.re.pandas
        assert data['space_left'] is None
        assert data['username'] == 'testuser'
        assert data['is_staff'] == True

    def test_data_when_response_is_none(self):
        response = Response(None, serialize=False)
        with pytest.raises(ValueError, match="No response data"):
            _ = response.data


class TestSession(unittest.TestCase):

    def setUp(self) -> None:
        self.session = Session(instance="test.qa4sm.eu", token="none")

    def test_login_fails(self):
        with pytest.raises(AuthenticationError):
            self.session.login_with_credentials(
                "asd", "asd")

    def test_url_pretty(self):
        url = self.session.url("asd", "jkl/")
        assert url == "https://test.qa4sm.eu/api/asd/jkl/"

        url = self.session.url("asd", "jkl")
        assert url == "https://test.qa4sm.eu/api/asd/jkl"

    @pytest.mark.skipif(QA4SM_ACCESS is None, reason="No credentials found.")
    def test_login(self):
        token = QA4SM_ACCESS[self.session.instance]['token']
        status_code = self.session.login_with_token(token)
        assert status_code == 200

    def test_token_auto_missing_dotrc(self):
        with patch.object(Access, 'from_available') as mock:
            mock.side_effect = FileNotFoundError("No dotrc")
            with pytest.warns(UserWarning, match="Continue as ANONYMOUS"):
                session = Session(instance="test.qa4sm.eu", token="auto")
            assert session.user == "ANONYMOUS"


class TestValidationConfiguration(unittest.TestCase):

    def setUp(self):
        self.config = ValidationConfiguration.from_remote(
            "9aeb663b-e24e-4541-8331-6ec3e0318d1f",
            instance="qa4sm.eu", token="none")

    def test_data_access(self):
        assert self.config['name_tag'] == "Test Case  QA4SM_VA_metrics - Test scaling_no_scaling_DEFAULT"
        assert self.config['interval_to'] == "2024-12-31"
        assert self.config['max_lon'] == 48.3
        assert self.config['min_lat'] == self.config.data['min_lat']

    def test_dump_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            self.config.dump(tmpdir / "config.json")
            also_config = ValidationConfiguration.from_file(
                tmpdir / "config.json")
            assert self.config == also_config

    def test_setitem_key_not_exists(self):
        config = ValidationConfiguration([{'key': 'value'}])
        with pytest.raises(KeyError, match="badkey"):
            config['badkey'] = 'new'


class TestConnectionTestInstance(unittest.TestCase):

    def setUp(self):
        self.con = Connection(instance="test.qa4sm.eu", token="None")

    def test_token_is_None(self):
        assert self.con.session.user == "ANONYMOUS"

    def test_get_datasets(self):
        ds = self.con.datasets()
        assert ds.loc[1, "short_name"] == 'C3S_combined'
        assert ds.columns.size > 2

    def test_get_dataset_id(self):
        id = self.con.dataset_id("C3S_combined")
        assert id == 1

    def test_get_versions(self):
        vers = self.con.versions("C3S_combined")
        alsovers = self.con.versions(1)
        assert vers.equals(alsovers)

    def test_get_version_info(self):
        vers = self.con.version_info(70)
        assert vers["short_name"] == "C3S_V202505"
        assert vers["id"] == 70

    def test_get_variable_info(self):
        id = 1
        var = self.con.variable_info(id)
        assert var["short_name"] == "sm"
        assert var["id"] == id

    def test_get_filter_info(self):
        id = 1
        fil = self.con.filter_info(id)
        assert fil["name"] == "FIL_ALL_VALID_RANGE"
        assert fil["parameterised"] == False
        assert fil["id"] == id

    def test_get_param_filter_info(self):
        id = 18
        fil = self.con.filter_info(id)
        assert fil["name"] == "FIL_ISMN_NETWORKS"
        assert fil["parameterised"] == True
        assert fil["id"] == id

    def test_get_period(self):
        start, end = self.con.get_period(70)
        assert pd.to_datetime(start) < pd.to_datetime(end)

    def test_download_results(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            val_id = "d9cf81c7-5c1c-4341-8a0c-4d6fcfb91677"
            self.con.download_results(val_id, out_dir=tmpdir,
                                      force_download=True)
            assert f"{val_id}.nc" in os.listdir(tmpdir)
            assert "summary_stats.csv" in os.listdir(tmpdir)
            assert "qa4sm_graphics" in os.listdir(tmpdir)
            assert len(os.listdir(Path(tmpdir) / "qa4sm_graphics")) > 0

    def test_find_multiple_matches(self):
        df = pd.DataFrame({'col': ['a', 'a']}, index=[1, 2])
        with pytest.raises(ValueError, match="Multiple"):
            self.con._find(df, 'a')



@pytest.mark.skipif(QA4SM_ACCESS is None,
                    reason="No Access credentials available.")
class TestConnectionWithToken(unittest.TestCase):

    def setUp(self):
        instance = "test.qa4sm.eu"
        token = QA4SM_ACCESS[instance]['token']
        self.con = Connection(instance=instance, token=token)

    def test_url(self):
        assert (self.con.url("asd", "jkl/") ==
                "https://test.qa4sm.eu/api/asd/jkl/")

        assert (self.con.url("asd", "jkl") ==
                "https://test.qa4sm.eu/api/asd/jkl")

    def test_user(self):
        user = self.con.user()
        assert user['auth_token'] == QA4SM_ACCESS[self.con.session.instance]['token']
        assert user['username'] == self.con.session.user

    def test_my_validation_runs(self):
        runs = self.con.my_validation_runs()
        assert isinstance(runs, pd.DataFrame)
        assert runs.index.name == "id"
        assert list(runs.columns) == ["name", "datasets", "progress"]

    def test_delete_validation(self):
        # dry run, dummy respone, validation doesn't actually exist
        response = self.con.delete("xx99999999999-9999-9999",
                                   dry_run=True)
        assert isinstance(response, Response)
        assert response.response.status_code == 200

    def test_run_config_validation_with_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, 'config.json')
            with open(config_path, 'w') as f:
                f.write('[{"name": "test", "value": 1}]')
            
            with patch.object(self.con, 'run_validation') as mock:
                mock.return_value = pd.Series({'id': 'run123'})
                self.con.run_config_validation(config_path, override={'value': 2})
                assert mock.called
    
    def test_run_config_validation_invalid_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, 'config.json')
            with open(config_path, 'w') as f:
                f.write('[{"name": "test"}]')
            
            with pytest.raises(KeyError, match="badkey"):
                self.con.run_config_validation(config_path, override={'badkey': 2})


class TestValidationMonitoring(unittest.TestCase):

    def setUp(self):
        self.con = Connection(instance="test.qa4sm.eu", token="None")
        self.run_id = "9aeb663b-e24e-4541-8331-6ec3e0318d1f"

    def test_validation_status_done_state(self):
        """Test validation status for DONE state"""
        with patch.object(self.con.session, 'get') as mock_get:
            mock_response = Mock()
            mock_response.data = [{'status': 'DONE', 'progress': 100}]
            self.con.session.get = lambda url, headers=None: mock_response
            
            status, progress = self.con.validation_status(self.run_id)
            assert status == 'DONE'
            assert progress == 100

    def test_validation_status_running_state(self):
        """Test validation status for RUNNING state"""
        with patch.object(self.con.session, 'get') as mock_get:
            mock_response = Mock()
            mock_response.data = [{'status': 'RUNNING', 'progress': 50}]
            self.con.session.get = lambda url, headers=None: mock_response
            
            status, progress = self.con.validation_status(self.run_id)
            assert status == 'RUNNING'
            assert progress == 50

    def test_validation_status_not_found(self):
        """Test validation status when run doesn't exist"""
        with patch.object(self.con.session, 'get') as mock_get:
            mock_get.side_effect = requests.exceptions.HTTPError(response=Mock(status_code=404))
            
            status, progress = self.con.validation_status(self.run_id)
            assert status == 'NOT FOUND'
            assert progress == 0

    def test_validation_time(self):
        """Test validation timing retrieval"""
        with patch.object(self.con.session, 'get') as mock_get:
            mock_response = Mock()
            mock_response.data = [{
                'start_time': '2024-03-24T10:00:00Z',
                'end_time': '2024-03-24T10:30:00Z'
            }]
            self.con.session.get = lambda url, headers=None: mock_response
            
            start_time, end_time = self.con.validation_time(self.run_id)
            assert start_time is not None
            assert end_time is not None
            assert end_time > start_time

    def test_validation_duration(self):
        """Test validation duration calculation"""
        with patch.object(self.con.session, 'get') as mock_get:
            mock_response = Mock()
            mock_response.data = [{
                'duration_seconds': 3600,
                'duration_format': '1h 0m 0s'
            }]
            self.con.session.get = lambda url, headers=None: mock_response
            
            seconds, formatted = self.con.validation_duration(self.run_id)
            assert seconds == 3600
            assert formatted == '1h 0m 0s'


class TestDownloadFunctionality(unittest.TestCase):

    def setUp(self):
        self.con = Connection(instance="test.qa4sm.eu", token="None")
        self.run_id = "9aeb663b-e24e-4541-8331-6ec3e0318d1f"
        self.test_config = {
            'name_tag': 'test',
            'interval_from': '2024-01-01',
            'interval_to': '2024-12-31'
        }

    def test_download_configuration(self):
        """Test downloading and saving validation configuration"""
        with patch.object(self.con.session, 'get') as mock_get:
            mock_response = Mock()
            mock_response.data = [self.test_config.copy()]
            self.con.session.get = lambda url, headers=None: mock_response
            
            config = self.con.download_configuration(self.run_id)
            assert config['name_tag'] == 'test'
            assert config['interval_from'] == '2024-01-01'


class TestErrorCases(unittest.TestCase):

    def setUp(self):
        self.con = Connection(instance="test.qa4sm.eu", token="None")
        self.run_id = "9aeb663b-e24e-4541-8331-6ec3e0318d1f"

    @patch('qa4sm_api.client_api.Connection.validation_exists',
           return_value=False)
    def test_validation_not_found_error(self, mock_exists):
        """Test ValidationRunNotFoundError is raised for invalid run ID"""
        with self.assertRaises(ValidationRunNotFoundError):
            self.con.validation_time(self.run_id)

    def test_validation_run_not_found_error(self):
        error = ValidationRunNotFoundError("run123")
        assert "run123" in str(error)

    def test_validation_instance_error(self):
        error = ValidationInstanceError("msg")
        assert "msg" in str(error)


class TestGlobalsDotrc(unittest.TestCase):
    """Test _write_dotrc and _load_dotrc"""

    def test_write_dotrc(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, '.qa4smapirc')
            _write_dotrc({"qa4sm.eu": {"token": "t1"}}, path)
            with open(path) as f:
                content = f.read()
            assert "qa4sm.eu" in content
            assert "t1" in content

    def test_load_dotrc_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="credentials file not found"):
            _load_dotrc("/nonexistent/.qa4smapirc")


class TestAccessEnv(unittest.TestCase):
    """Test Access.from_env"""

    def test_from_env_success(self):
        with patch.dict(os.environ, {
            "QA4SM_INSTANCE": "test.qa4sm.eu",
            "QA4SM_TOKEN": "test_token"
        }):
            access = Access.from_env()
            assert access.access["test.qa4sm.eu"] == {"token": "test_token"}


def test_unknown_instance():
    with pytest.warns(UserWarning):
        conn = Connection("unknown_instance.com", token="none")
    with pytest.raises(requests.exceptions.ConnectionError):
        conn.datasets()

if __name__ == '__main__':
    test_unknown_instance()
    #connection = TestConnectionWithToken()
    #connection.setUp()
    #connection.test_url()
