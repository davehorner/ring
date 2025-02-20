import sys
import os
import re
import requests
import tarfile
import subprocess
import shutil
import stat

CRATE_NAME = "ring"
BASE_URL = "https://crates.io"
CRATES_DIR = os.path.join(os.getcwd(), "crates")
EVENTSOURCE_REPO = "https://github.com/launchdarkly/rust-eventsource-client.git"
#EVENTSOURCE_REPO = "git@github.com:davehorner/rust-eventsource-client.git"

def handle_remove_readonly(func, path, exc_info):
    # Change the file to be writable and try again.
    os.chmod(path, stat.S_IWRITE)
    func(path)

def get_versions(crate_name):
    url = f"{BASE_URL}/api/v1/crates/{crate_name}/versions"
    response = requests.get(url)
    response.raise_for_status()
    data = response.json()
    return data.get("versions", [])

def get_version_info(crate_name, target_version):
    versions = get_versions(crate_name)
    if target_version == "latest":
        if not versions:
            return None
        return versions[0]
    else:
        for version in versions:
            if version.get("num") == target_version:
                return version
    return None

def download_crate(download_url, dest_path):
    response = requests.get(download_url, stream=True)
    response.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    print(f"Downloaded crate to {dest_path}")

def extract_crate(archive_path, extract_dir):
    if os.path.exists(extract_dir):
        shutil.rmtree(extract_dir, onerror=handle_remove_readonly)
        print(f"Removed existing directory: {extract_dir}")
    os.makedirs(extract_dir, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(path=extract_dir)
    print(f"Extracted crate to {extract_dir}")
    extracted_dirs = [d for d in os.listdir(extract_dir) if os.path.isdir(os.path.join(extract_dir, d))]
    if extracted_dirs:
        return os.path.join(extract_dir, extracted_dirs[0])
    else:
        return extract_dir

def patch_cargo_toml_for_workspace(crate_source_dir):
    cargo_toml_path = os.path.join(crate_source_dir, "Cargo.toml")
    if not os.path.exists(cargo_toml_path):
        print("Cargo.toml not found; cannot patch workspace settings.")
        return
    with open(cargo_toml_path, "r") as f:
        content = f.read()
    if "[workspace]" in content:
        print("Cargo.toml already contains a [workspace] section; no patch needed.")
        return
    patched_content = content.rstrip() + "\n\n[workspace]\n"
    with open(cargo_toml_path, "w") as f:
        f.write(patched_content)
    print("Patched Cargo.toml with an empty [workspace] table.")

def build_crate(crate_dir, build_cmd=["cargo", "build"]):
    print(f"Running '{' '.join(build_cmd)}' in {crate_dir} ...")
    proc = subprocess.Popen(
        build_cmd,
        cwd=crate_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    output, _ = proc.communicate()
    return output

def sanitize_output(text):
    home_dir = os.path.expanduser("~")
    cwd = os.getcwd()
    sanitized = text.replace(home_dir, "<HOME>")
    sanitized = sanitized.replace(cwd, "<CWD>")
    sanitized = re.sub(r'/home/([^/]+)', r'/home/<USER>', sanitized)
    return sanitized

def clone_eventsource(eventsource_dir):
    if os.path.exists(eventsource_dir):
        shutil.rmtree(eventsource_dir, onerror=handle_remove_readonly)
        print(f"Removed existing eventsource directory: {eventsource_dir}")
    print(f"Cloning eventsource client from {EVENTSOURCE_REPO} into {eventsource_dir}...")
    proc = subprocess.Popen(
        ["git", "clone", EVENTSOURCE_REPO, eventsource_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    out, _ = proc.communicate()
    print(out)

def patch_eventsource_dependency(ring_path, eventsource_dir):
    cargo_toml_path = os.path.join(eventsource_dir, "Cargo.toml")
    if not os.path.exists(cargo_toml_path):
        print("Eventsource client Cargo.toml not found!")
        return
    real_ring_path = os.path.abspath(ring_path).replace("\\", "/")
    with open(cargo_toml_path, "r") as f:
        content = f.read()
    patch_section = f"\n[patch.crates-io]\nring = {{ path = \"{real_ring_path}\" }}\n"
    if "[patch.crates-io]" in content:
        content = re.sub(r'ring\s*=\s*\{[^}]+\}', f'ring = {{ path = \"{real_ring_path}\" }}', content)
        print("Updated existing [patch.crates-io] entry for ring.")
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += patch_section
        print("Added new [patch.crates-io] section for ring.")
    with open(cargo_toml_path, "w") as f:
        f.write(content)
    print(f"Patched {cargo_toml_path} to use ring at {real_ring_path}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <version|latest>")
        sys.exit(1)

    target_version = sys.argv[1]
    version_info = get_version_info(CRATE_NAME, target_version)
    if not version_info:
        print(f"Version {target_version} not found for crate '{CRATE_NAME}'.")
        sys.exit(1)

    version_num = version_info.get("num")
    dl_path = version_info.get("dl_path")
    if not dl_path:
        print("Download path not found in version info.")
        sys.exit(1)

    download_url = BASE_URL + dl_path
    print(f"Selected ring version: {version_num}")
    print(f"Download URL: {download_url}")
    os.makedirs(CRATES_DIR, exist_ok=True)

    archive_filename = f"{CRATE_NAME}-{version_num}.crate"
    archive_path = os.path.join(CRATES_DIR, archive_filename)
    extract_dir = os.path.join(CRATES_DIR, f"{CRATE_NAME}-{version_num}")

    download_crate(download_url, archive_path)
    crate_source_dir = extract_crate(archive_path, extract_dir)
    patch_cargo_toml_for_workspace(crate_source_dir)

    ring_build_output = build_crate(crate_source_dir)
    raw_ring_output_file = os.path.join(CRATES_DIR, f"build_output_{CRATE_NAME}_{version_num}.txt")
    with open(raw_ring_output_file, "w") as f:
        f.write(ring_build_output)
    print(f"Raw ring build output written to {raw_ring_output_file}")

    sanitized_ring_output = sanitize_output(ring_build_output)
    sanitized_ring_output_file = os.path.join(CRATES_DIR, f"build_output_{CRATE_NAME}_{version_num}_sanitized.txt")
    with open(sanitized_ring_output_file, "w") as f:
        f.write(sanitized_ring_output)
    print(f"Sanitized ring build output written to {sanitized_ring_output_file}")

    print("\n=== Processing eventsource client ===")
    eventsource_dir = os.path.join(CRATES_DIR, f"rust-eventsource-client_{version_num}")
    clone_eventsource(eventsource_dir)
    patch_eventsource_dependency(crate_source_dir, eventsource_dir)

    eventsource_build_output = build_crate(eventsource_dir, build_cmd=["cargo", "build"])
    raw_eventsource_output_file = os.path.join(CRATES_DIR, f"build_output_eventsource_client_{version_num}.txt")
    with open(raw_eventsource_output_file, "w") as f:
        f.write(eventsource_build_output)
    print(f"Raw eventsource client build output written to {raw_eventsource_output_file}")

    sanitized_eventsource_output = sanitize_output(eventsource_build_output)
    sanitized_eventsource_output_file = os.path.join(CRATES_DIR, f"build_output_eventsource_client_{version_num}_sanitized.txt")
    with open(sanitized_eventsource_output_file, "w") as f:
        f.write(sanitized_eventsource_output)
    print(f"Sanitized eventsource client build output written to {sanitized_eventsource_output_file}")

if __name__ == "__main__":
    main()

