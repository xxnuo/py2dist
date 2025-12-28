import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Optional

from py2dist.template import BUILD_SCRIPT_TEMPLATE


@dataclass
class CompileOptions:
    python_version: str = ""
    source_file: Optional[str] = None
    source_dir: Optional[str] = None
    exclude_files: list = field(default_factory=list)
    nthread: int = 1
    quiet: bool = False
    release: bool = False
    output_dir: str = "dist"
    ccache: Optional[str] = None


def find_ccache() -> Optional[str]:
    ccache_path = shutil.which("ccache")
    if ccache_path:
        return ccache_path
    common_paths = [
        "/usr/bin/ccache",
        "/usr/local/bin/ccache",
        "/opt/homebrew/bin/ccache",
    ]
    for path in common_paths:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


IS_WINDOWS = platform.system() == "Windows"


def get_files_in_dir(
    dir_path: str,
    include_subfolder: bool = True,
    path_type: int = 0,
    ext_names: str | list = "*",
):
    if isinstance(ext_names, str) and ext_names != "*":
        ext_names = [ext_names]
    if isinstance(ext_names, list):
        ext_names = [e.lower() for e in ext_names]

    def match_ext(filename):
        if isinstance(ext_names, list):
            ext = (
                filename if filename.startswith(".") else os.path.splitext(filename)[1]
            )
            return ext.lower() in ext_names
        return True

    if include_subfolder:
        base_len = len(dir_path)
        for root, _, files in os.walk(dir_path):
            for fname in files:
                if not match_ext(fname):
                    continue
                if path_type == 0:
                    yield os.path.join(root, fname)
                elif path_type == 1:
                    yield os.path.join(root[base_len:].lstrip(os.path.sep), fname)
                else:
                    yield fname
    else:
        for fname in os.listdir(dir_path):
            fpath = os.path.join(dir_path, fname)
            if os.path.isfile(fpath) and match_ext(fname):
                yield fpath if path_type == 0 else fname


def make_dirs(dirpath: str):
    dirpath = dirpath.strip().rstrip(os.path.sep)
    if dirpath and not os.path.exists(dirpath):
        os.makedirs(dirpath)


class Compiler:
    def __init__(self, options: Optional[CompileOptions] = None):
        self.options = options or CompileOptions()
        self._validate_options()
        self._work_dir = os.getcwd()
        self._temp_dir = None

    def _validate_options(self):
        if self.options.source_file and self.options.source_dir:
            raise ValueError("Cannot use both source_file and source_dir")
        if not self.options.source_file and not self.options.source_dir:
            raise ValueError("Must specify source_file or source_dir")

    def _get_compile_files(self) -> list:
        files = []
        opts = self.options

        if opts.source_dir:
            if not os.path.exists(opts.source_dir):
                raise FileNotFoundError(f"Directory not found: {opts.source_dir}")

            pyfiles = list(
                get_files_in_dir(
                    dir_path=opts.source_dir,
                    include_subfolder=True,
                    path_type=1,
                    ext_names=".py",
                )
            )
            pyfiles = [f for f in pyfiles if not f.endswith("__init__.py")]
            pyfiles = list(set(pyfiles) - set(opts.exclude_files))
            files = [os.path.join(opts.source_dir, f) for f in pyfiles]

        if opts.source_file:
            if not opts.source_file.endswith(".py"):
                raise ValueError("Source file must be a .py file")
            if not os.path.exists(opts.source_file):
                raise FileNotFoundError(f"File not found: {opts.source_file}")
            files.append(opts.source_file)

        return files

    def _get_non_compile_files(self, compile_files: list) -> list:
        if not self.options.source_dir:
            return []

        all_files = list(
            get_files_in_dir(
                dir_path=self.options.source_dir,
                include_subfolder=True,
                path_type=1,
                ext_names="*",
            )
        )
        all_files = [
            os.path.join(self.options.source_dir, f)
            for f in all_files
            if not f.endswith(".pyc")
        ]
        return list(set(all_files) - set(compile_files))

    def _generate_build_script(self, files: list):
        files_repr = repr(files)
        content = BUILD_SCRIPT_TEMPLATE % (
            files_repr,
            self.options.python_version,
            self.options.nthread,
            self.options.quiet,
        )
        script_dir = os.path.join(self._work_dir, ".py2dist")
        make_dirs(script_dir)
        script_path = os.path.join(script_dir, "build.py")
        with open(script_path, "w") as f:
            f.write(content)
        return script_path

    def _clear_build_folders(self):
        for folder in [
            ".py2dist/build",
            ".py2dist/build_c",
            self.options.output_dir,
        ]:
            folder_path = os.path.join(self._work_dir, folder)
            if os.path.isdir(folder_path):
                shutil.rmtree(folder_path)

    def _clear_tmp_files(self):
        folder_path = os.path.join(self._work_dir, ".py2dist")
        if os.path.isdir(folder_path):
            shutil.rmtree(folder_path)

    def _run_cython_build(self, script_path: str):
        build_dir = os.path.join(self._work_dir, ".py2dist/build")
        build_c_dir = os.path.join(self._work_dir, ".py2dist/build_c")
        make_dirs(build_dir)
        make_dirs(build_c_dir)

        env = os.environ.copy()
        ccache_path = self.options.ccache
        if not ccache_path:
            ccache_path = find_ccache()
        
        if ccache_path:
            env["CC"] = f"{ccache_path} {env.get('CC', 'gcc')}"
            env["CXX"] = f"{ccache_path} {env.get('CXX', 'g++')}"
            if not self.options.quiet:
                print(f"Using ccache: {ccache_path}")

        log = "> log.txt" if self.options.quiet else ""
        py_cmd = (
            "python"
            if not self.options.python_version
            else f"python{self.options.python_version}"
        )
        cmd = f"{py_cmd} {script_path} {self._work_dir} build_ext --build-lib={build_dir} --build-temp={build_c_dir} {log} --parallel=8"

        if not IS_WINDOWS and not self.options.quiet:
            print(f"> {cmd}")

        p = subprocess.Popen(
            cmd, shell=True, stderr=subprocess.STDOUT, cwd=self._work_dir, env=env
        )
        code = p.wait()
        if code:
            raise RuntimeError("Cython build failed")

    def _collect_output(self, compile_files: list):
        output_dir = os.path.join(self._work_dir, self.options.output_dir)
        build_dir = os.path.join(self._work_dir, ".py2dist/build")
        make_dirs(output_dir)

        for file in get_files_in_dir(build_dir, True, 1, [".so", ".pyd"]):
            src_path = os.path.join(build_dir, file)
            parts = file.split(os.path.sep)
            name_parts = os.path.basename(src_path).split(".")
            file_name = ".".join([name_parts[0]] + name_parts[-1:])
            mid_path = os.path.sep.join(parts[:-1])
            dest_path = os.path.join(output_dir, mid_path, file_name)
            make_dirs(os.path.dirname(dest_path))
            shutil.copy(src_path, dest_path)

        for non_compile_file in self._get_non_compile_files(compile_files):
            dest_path = os.path.join(output_dir, non_compile_file)
            make_dirs(os.path.dirname(dest_path))
            shutil.copyfile(os.path.join(self._work_dir, non_compile_file), dest_path)

    def compile(self) -> str:
        compile_files = self._get_compile_files()
        if not compile_files:
            raise ValueError("No files to compile")

        self._clear_build_folders()
        self._temp_dir = tempfile.mkdtemp()

        try:
            if IS_WINDOWS:
                for file in compile_files:
                    script_path = self._generate_build_script([file])
                    self._run_cython_build(script_path)
            else:
                script_path = self._generate_build_script(compile_files)
                self._run_cython_build(script_path)

            self._collect_output(compile_files)

            if self.options.release:
                self._clear_tmp_files()
        finally:
            if self._temp_dir and os.path.exists(self._temp_dir):
                shutil.rmtree(self._temp_dir)

        return self.options.output_dir


def compile_file(
    source: str,
    output_dir: str = "dist",
    python_version: str = "",
    nthread: int = 1,
    quiet: bool = False,
    release: bool = True,
) -> str:
    opts = CompileOptions(
        source_file=source,
        output_dir=output_dir,
        python_version=python_version,
        nthread=nthread,
        quiet=quiet,
        release=release,
    )
    return Compiler(opts).compile()


def compile_dir(
    source: str,
    output_dir: str = "dist",
    exclude: Optional[list] = None,
    python_version: str = "",
    nthread: int = 1,
    quiet: bool = False,
    release: bool = True,
) -> str:
    source = source.rstrip("/")
    opts = CompileOptions(
        source_dir=source,
        output_dir=output_dir,
        exclude_files=exclude or [],
        python_version=python_version,
        nthread=nthread,
        quiet=quiet,
        release=release,
    )
    return Compiler(opts).compile()
