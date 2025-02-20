import sys
import os
import re
import requests
import tarfile
import subprocess
import shutil

CRATE_NAME = "ring"
BASE_URL = "https://crates.io"
CRATES_DIR = os.path.join(os.getcwd(), "crates")

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
        # Assume the API returns versions in descending order (most recent first)
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
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(path=extract_dir)
    print(f"Extracted crate to {extract_dir}")
    # The archive typically extracts to a folder named "crate_name-version"
    extracted_dirs = [d for d in os.listdir(extract_dir) if os.path.isdir(os.path.join(extract_dir, d))]
    if extracted_dirs:
        return os.path.join(extract_dir, extracted_dirs[0])
    else:
        return extract_dir

def patch_cargo_toml(crate_source_dir):
    """
    Patch the Cargo.toml file by adding an empty [workspace] table if it doesn't already have one.
    This prevents Cargo from trying to associate the crate with a parent workspace.
    """
    cargo_toml_path = os.path.join(crate_source_dir, "Cargo.toml")
    if not os.path.exists(cargo_toml_path):
        print("Cargo.toml not found; cannot patch workspace settings.")
        return

    with open(cargo_toml_path, "r") as f:
        content = f.read()

    if "[workspace]" in content:
        print("Cargo.toml already contains a [workspace] section; no patch needed.")
        return

    # Append an empty [workspace] table at the end of the file.
    patched_content = content.rstrip() + "\n\n[workspace]\n"
    with open(cargo_toml_path, "w") as f:
        f.write(patched_content)
    print("Patched Cargo.toml with an empty [workspace] table.")

def build_crate(crate_dir):
    print(f"Building crate in {crate_dir} ...")
    proc = subprocess.Popen(
        ["cargo", "build"],
        cwd=crate_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    output, _ = proc.communicate()
    return output

def sanitize_output(text):
    # Remove absolute paths that may contain the current user's home directory or current working directory.
    home_dir = os.path.expanduser("~")
    cwd = os.getcwd()
    sanitized = text.replace(home_dir, "<HOME>")
    sanitized = sanitized.replace(cwd, "<CWD>")
    # Optionally, remove any username occurrences (assuming username is part of a /home path)
    sanitized = re.sub(r'/home/([^/]+)', r'/home/<USER>', sanitized)
    return sanitized

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
    print(f"Selected version: {version_num}")
    print(f"Download URL: {download_url}")

    # Create the persistent crates directory if it doesn't exist
    os.makedirs(CRATES_DIR, exist_ok=True)

    # Prepare paths for downloading and extraction
    archive_filename = f"{CRATE_NAME}-{version_num}.crate"
    archive_path = os.path.join(CRATES_DIR, archive_filename)
    extract_dir = os.path.join(CRATES_DIR, f"{CRATE_NAME}-{version_num}")

    # Download the crate tarball
    download_crate(download_url, archive_path)

    # Extract the crate if not already extracted
    if not os.path.exists(extract_dir):
        os.makedirs(extract_dir, exist_ok=True)
        crate_source_dir = extract_crate(archive_path, extract_dir)
    else:
        extracted_dirs = [d for d in os.listdir(extract_dir) if os.path.isdir(os.path.join(extract_dir, d))]
        crate_source_dir = os.path.join(extract_dir, extracted_dirs[0]) if extracted_dirs else extract_dir

    # Patch Cargo.toml to add an empty [workspace] table to avoid workspace conflicts
    patch_cargo_toml(crate_source_dir)

    # Build the crate and capture output
    build_output = build_crate(crate_source_dir)

    # Write raw build output to a file
    raw_output_file = os.path.join(CRATES_DIR, f"build_output_{CRATE_NAME}_{version_num}.txt")
    with open(raw_output_file, "w") as f:
        f.write(build_output)
    print(f"Raw build output written to {raw_output_file}")

    # Sanitize the output and write to a separate file
    sanitized_output = sanitize_output(build_output)
    sanitized_output_file = os.path.join(CRATES_DIR, f"build_output_{CRATE_NAME}_{version_num}_sanitized.txt")
    with open(sanitized_output_file, "w") as f:
        f.write(sanitized_output)
    print(f"Sanitized build output written to {sanitized_output_file}")

if __name__ == "__main__":
    main()

