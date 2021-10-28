# (c) 2012-2019, Ansible by Red Hat
#
# This file is part of Ansible Galaxy
#
# Ansible Galaxy is free software: you can redistribute it and/or modify
# it under the terms of the Apache License as published by
# the Apache Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# Ansible Galaxy is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# Apache License for more details.
#
# You should have received a copy of the Apache License
# along with Galaxy.  If not, see <http://www.apache.org/licenses/>.

import json
import logging
import os
import re
import tempfile
from types import SimpleNamespace
from unittest import mock

import attr
import pytest

from galaxy_importer import collection
from galaxy_importer.collection import CollectionLoader
from galaxy_importer.constants import ContentType
from galaxy_importer import exceptions as exc
from galaxy_importer import schema
from galaxy_importer.utils import chksums as chksums_utils
from galaxy_importer.utils import markup as markup_utils

log = logging.getLogger(__name__)

MANIFEST_JSON = """
{
 "collection_info": {
  "namespace": "my_namespace",
  "name": "my_collection",
  "version": "2.0.2",
  "authors": [
   "John Doe"
  ],
  "readme": "README.md",
  "tags": [
   "deployment",
   "fedora"
  ],
  "description": "A collection with various roles and plugins",
  "license": [
   "GPL-3.0-or-later",
   "MIT"
  ],
  "license_file": null,
  "dependencies": {
   "my_namespace.collection_nginx": ">=0.1.6",
   "network_user.collection_inspect": "2.0.0",
   "dave.deploy": "*"
  },
  "repository": "http://example.com/repository",
  "documentation": null,
  "homepage": null,
  "issues": null
 },
 "file_manifest_file": {
  "name": "FILES.json",
  "ftype": "file",
  "chksum_type": "sha256",
  "chksum_sha256": "0c2e9514f54aaeda0605d8c9a60e71cab3e577113b58ecc65b839d2d1b86c216",
  "format": 1
 }
}
"""

FILES_JSON = """
{
 "format": 1,
 "files": [
  {
   "name": ".",
   "ftype": "dir",
   "chksum_type": null,
   "chksum_sha256": null,
   "format": 1
  },
  {
   "name": "LICENSE",
   "ftype": "file",
   "chksum_type": "sha256",
   "chksum_sha256": "af995cae1eec804d1c0423888d057eefe492f7d8f06a4672be45112927b37929",
   "format": 1
  },
  {
   "name": "README.md",
   "ftype": "file",
   "chksum_type": "sha256",
   "chksum_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
   "format": 1
  },
  {
   "name": "meta",
   "ftype": "dir",
   "chksum_type": null,
   "chksum_sha256": null,
   "format": 1
  },
  {
   "name": "meta/runtime.yml",
   "ftype": "file",
   "chksum_type": "sha256",
   "chksum_sha256": "2feceaa030f25bd5ff0e44b5935a8ad870d334dcca6c7c7df32eaab10eaea20c",
   "format": 1
  }
 ]
}
"""

LICENSE_FILE = """
This collection is public domain. No rights Reserved.
"""

META_RUNTIME_YAML = """
requires_ansible: '>=2.9.10,<2.11.5'
plugin_routing:
  modules:
    set_config:
      redirect: my_ns.devops.devops_set_config
      deprecation:
        removal_date: '2022-06-01'
        warning_text: See the plugin documentation for more details
"""


@pytest.fixture
def tmp_collection_root():
    import shutil

    try:
        tmp_dir = tempfile.TemporaryDirectory().name
        sub_path = "ansible_collections/placeholder_namespace/placeholder_name"
        collection_root = os.path.join(tmp_dir, sub_path)
        os.makedirs(collection_root)
        os.makedirs(os.path.join(collection_root, "meta"))
        yield collection_root
    finally:
        shutil.rmtree(tmp_dir)


@pytest.fixture
def populated_collection_root(tmp_collection_root):
    with open(os.path.join(tmp_collection_root, "MANIFEST.json"), "w") as fh:
        fh.write(MANIFEST_JSON)
    with open(os.path.join(tmp_collection_root, "README.md"), "w"):
        pass
    with open(os.path.join(tmp_collection_root, "FILES.json"), "w") as fh:
        fh.write(FILES_JSON)
    with open(os.path.join(tmp_collection_root, "LICENSE"), "w") as fh:
        fh.write(LICENSE_FILE)
    with open(os.path.join(tmp_collection_root, "meta", "runtime.yml"), "w") as fh:
        fh.write(META_RUNTIME_YAML)
    return tmp_collection_root


@pytest.fixture
def readme_artifact_file(request):
    marker = request.node.get_closest_marker("sha256")
    sha256 = marker.args[0]
    artifact_file = schema.CollectionArtifactFile(
        name="README.md",
        ftype="file",
        chksum_type="sha256",
        chksum_sha256=sha256,
        format=1,
    )

    return artifact_file


@pytest.mark.sha256("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
def test_check_artifact_file(populated_collection_root, readme_artifact_file):
    res = chksums_utils.check_artifact_file(populated_collection_root, readme_artifact_file)
    log.debug("res: %s", res)
    assert res is True


@pytest.mark.sha256("deadbeef98fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
def test_check_artifact_file_bad_chksum(populated_collection_root, readme_artifact_file):
    with pytest.raises(
        exc.CollectionArtifactFileChecksumError,
        match=r"File README.md.*but the.*actual sha256sum was.*",
    ):
        chksums_utils.check_artifact_file(populated_collection_root, readme_artifact_file)


@mock.patch("galaxy_importer.collection.CollectionLoader._build_docs_blob")
def test_manifest_success(_build_docs_blob, populated_collection_root):
    _build_docs_blob.return_value = {}

    filename = collection.CollectionFilename("my_namespace", "my_collection", "2.0.2")
    data = CollectionLoader(
        populated_collection_root,
        filename,
        cfg=SimpleNamespace(run_ansible_doc=True),
    ).load()
    assert data.metadata.namespace == "my_namespace"
    assert data.metadata.name == "my_collection"
    assert data.metadata.version == "2.0.2"
    assert data.metadata.authors == ["John Doe"]
    assert data.metadata.readme == "README.md"
    assert data.metadata.tags == ["deployment", "fedora"]
    assert data.metadata.description == "A collection with various roles and plugins"
    assert data.metadata.license_file is None
    assert data.metadata.dependencies == {
        "my_namespace.collection_nginx": ">=0.1.6",
        "network_user.collection_inspect": "2.0.0",
        "dave.deploy": "*",
    }
    assert data.metadata.repository == "http://example.com/repository"
    assert data.metadata.homepage is None
    assert data.metadata.issues is None


@pytest.mark.parametrize(
    "manifest_text,new_text,error_subset",
    [
        ("my_namespace", "", "'namespace' is required"),
        ("my_namespace", "00my.name.space", "'namespace' has invalid format"),
        ("my_collection", "", "'name' is required"),
        ("my_collection", "_my_collection", "'name' has invalid format"),
        ("2.0.2", "", "'version' is required"),
        ("2.0.2", "2.2.0.0.2", "semantic version format"),
        ('"John Doe"', "", "'authors' is required"),
        ('[\n   "John Doe"\n  ]', '"John Doe"', "to be a list of strings"),
        ("README.md", "", "'readme' is required"),
        ('"fedora"', '["fedora"]', "to be a list of strings"),
        ('"deployment",', '"tag",' * 30, "Expecting no more than 20 tags"),
        ('"A collection with various roles and plugins"', "[]", "be a string"),
        ('"MIT"', "{}", "to be a list of strings"),
        ('"MIT"', '"not-a-valid-license-id"', "list of valid SPDX license"),
        ('"*"', "555", "Expecting depencency version to be string"),
        ('"dave.deploy"', '"davedeploy"', "Invalid dependency format:"),
        ('"dave.deploy"', '"007.deploy"', "Invalid dependency format: '007'"),
        ('"dave.deploy"', '"my_namespace.my_collection"', "self dependency"),
        ('"*"', '"3.4.0.4"', "version spec range invalid"),
        ('"http://example.com/repository"', '["repo"]', "must be a string"),
        ('"http://example.com/repository"', "null", "'repository' is required"),
        ('"documentation": null', '"documentation": []', "must be a string"),
        ('"homepage": null', '"homepage": []', "must be a string"),
        ('"issues": null', '"issues": []', "must be a string"),
    ],
)
def test_manifest_fail(manifest_text, new_text, error_subset, tmp_collection_root):
    manifest_edited = MANIFEST_JSON.replace(manifest_text, new_text)
    with open(os.path.join(tmp_collection_root, "MANIFEST.json"), "w") as fh:
        fh.write(manifest_edited)

    with pytest.raises(exc.ManifestValidationError, match=error_subset):
        CollectionLoader(tmp_collection_root, "my_namespace-my_collection-2.0.2.tar.gz").load()


def test_build_contents_blob():
    collection_loader = CollectionLoader("/tmpdir", "filename")
    collection_loader.content_objs = [
        schema.Content(name="my_module", content_type=ContentType.MODULE),
        schema.Content(name="my_role", content_type=ContentType.ROLE),
    ]
    res = collection_loader._build_contents_blob()
    assert [attr.asdict(item) for item in res] == [
        {"content_type": "module", "description": None, "name": "my_module"},
        {"content_type": "role", "description": None, "name": "my_role"},
    ]


@mock.patch("galaxy_importer.utils.markup.get_html")
@mock.patch("galaxy_importer.utils.markup.get_readme_doc_file")
def test_build_docs_blob_contents(get_readme_doc_file, get_html):
    get_readme_doc_file.return_value.name = "README.md"
    get_html.return_value = "<p>A detailed guide</p>"
    collection_loader = CollectionLoader(
        "/tmpdir", "filename", cfg=SimpleNamespace(run_ansible_doc=True)
    )
    collection_loader.content_objs = [
        schema.Content(name="my_module", content_type=ContentType.MODULE),
        schema.Content(name="my_role", content_type=ContentType.ROLE),
    ]
    res = collection_loader._build_docs_blob()
    assert attr.asdict(res) == {
        "collection_readme": {"name": "README.md", "html": "<p>A detailed guide</p>"},
        "documentation_files": [],
        "contents": [
            {
                "content_name": "my_module",
                "content_type": "module",
                "doc_strings": {},
                "readme_file": None,
                "readme_html": None,
            },
            {
                "content_name": "my_role",
                "content_type": "role",
                "doc_strings": {},
                "readme_file": None,
                "readme_html": None,
            },
        ],
    }


@mock.patch("galaxy_importer.utils.markup.get_html")
@mock.patch("galaxy_importer.utils.markup.get_readme_doc_file")
@mock.patch("galaxy_importer.utils.markup.get_doc_files")
def test_build_docs_blob_doc_files(get_doc_files, get_readme, get_html):
    get_readme.return_value.name = "README.md"
    get_html.return_value = "<p>A detailed guide</p>"
    get_doc_files.return_value = [
        markup_utils.DocFile(name="INTRO.md", text="Intro text", mimetype="text/markdown", hash=""),
        markup_utils.DocFile(
            name="INTRO2.md", text="Intro text", mimetype="text/markdown", hash=""
        ),
    ]
    collection_loader = CollectionLoader(
        "/tmpdir", "filename", cfg=SimpleNamespace(run_ansible_doc=True)
    )
    collection_loader.content_objs = []
    res = collection_loader._build_docs_blob()
    assert attr.asdict(res) == {
        "collection_readme": {"name": "README.md", "html": "<p>A detailed guide</p>"},
        "documentation_files": [
            {
                "name": "INTRO.md",
                "html": "<p>A detailed guide</p>",
            },
            {
                "name": "INTRO2.md",
                "html": "<p>A detailed guide</p>",
            },
        ],
        "contents": [],
    }

    collection_loader = CollectionLoader(
        "/tmpdir", "filename", cfg=SimpleNamespace(run_ansible_doc=False)
    )
    collection_loader.content_objs = []
    res = collection_loader._build_docs_blob()
    assert attr.asdict(res) == {
        "collection_readme": {"name": None, "html": None},
        "documentation_files": [],
        "contents": [],
    }


@mock.patch("galaxy_importer.utils.markup.get_readme_doc_file")
def test_build_docs_blob_no_readme(get_readme_doc_file):
    get_readme_doc_file.return_value = None
    collection_loader = CollectionLoader(
        "/tmpdir", "filename", cfg=SimpleNamespace(run_ansible_doc=True)
    )
    collection_loader.content_objs = []
    with pytest.raises(exc.ImporterError):
        collection_loader._build_docs_blob()


@mock.patch("galaxy_importer.collection.CollectionLoader._build_docs_blob")
def test_filename_empty_value(_build_docs_blob, populated_collection_root):
    _build_docs_blob.return_value = {}

    filename = collection.CollectionFilename(
        namespace="my_namespace", name="my_collection", version=None
    )
    data = CollectionLoader(
        populated_collection_root,
        filename,
        cfg=SimpleNamespace(run_ansible_doc=True),
    ).load()
    assert data.metadata.namespace == "my_namespace"
    assert data.metadata.name == "my_collection"
    assert data.metadata.version == "2.0.2"


@mock.patch("galaxy_importer.collection.CollectionLoader._build_docs_blob")
def test_filename_none(_build_docs_blob, populated_collection_root):
    _build_docs_blob.return_value = {}

    filename = None
    data = CollectionLoader(
        populated_collection_root,
        filename,
        cfg=SimpleNamespace(run_ansible_doc=True),
    ).load()
    assert data.metadata.namespace == "my_namespace"
    assert data.metadata.name == "my_collection"
    assert data.metadata.version == "2.0.2"


def test_filename_not_match_metadata(populated_collection_root):
    filename = collection.CollectionFilename("diff_ns", "my_collection", "2.0.2")
    with pytest.raises(exc.ManifestValidationError):
        CollectionLoader(populated_collection_root, filename).load()


def test_license_file(populated_collection_root):
    with open(os.path.join(populated_collection_root, "MANIFEST.json"), "w") as fh:
        manifest = json.loads(MANIFEST_JSON)
        manifest["collection_info"]["license"] = []
        manifest["collection_info"]["license_file"] = "LICENSE"
        fh.write(json.dumps(manifest))

    data = CollectionLoader(
        populated_collection_root,
        filename=None,
        cfg=SimpleNamespace(run_ansible_doc=True),
    ).load()
    assert data.metadata.license_file == "LICENSE"


def test_missing_readme(populated_collection_root):
    os.unlink(os.path.join(populated_collection_root, "README.md"))

    with pytest.raises(
        exc.CollectionArtifactFileNotFound,
        match=re.escape(r"The file (README.md) was not found"),
    ) as excinfo:
        CollectionLoader(populated_collection_root, filename=None).load()
    assert "README.md" == excinfo.value.missing_file


def test_manifest_json_with_no_files_json_info(populated_collection_root):
    # Modify MANIFEST.json so it doesn't reference a FILES.json
    manifest_json_obj = json.loads(MANIFEST_JSON)
    del manifest_json_obj["file_manifest_file"]
    with open(os.path.join(populated_collection_root, "MANIFEST.json"), "w") as fh:
        fh.write(json.dumps(manifest_json_obj))

    # MANIFEST.json did not contain a 'file_manifest_file' item pointing to FILES.json
    msg_match = "MANIFEST.json did not contain a 'file_manifest_file' item pointing to FILES.json"
    with pytest.raises(exc.ManifestValidationError, match=msg_match) as excinfo:

        CollectionLoader(populated_collection_root, filename=None).load()

    # pytest.raises ensures the outer exeption is a ManifestValidationError, this
    # asserts that the inner exceptions are a ValueError and a KeyError
    assert isinstance(excinfo.value.__cause__, ValueError)
    assert isinstance(excinfo.value.__cause__.__cause__, KeyError)


def test_unaccounted_for_files(populated_collection_root):
    extras = ["whatever.py.finalVerForReal", "a.out", "debug.log", ".oops-a-secret"]
    for extra in extras:
        with open(os.path.join(populated_collection_root, extra), "w"):
            pass

    filename = None
    with pytest.raises(
        exc.FileNotInFileManifestError,
        match="Files in the artifact but not the file manifest:",
    ) as excinfo:
        CollectionLoader(
            populated_collection_root,
            filename,
            cfg=SimpleNamespace(run_ansible_doc=True),
        ).load()
    assert "a.out" in excinfo.value.unexpected_files