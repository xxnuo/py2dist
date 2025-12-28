import compileall
import os
import platform
import py_compile
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
    debug: bool = False
    output_dir: str = "dist"
    ccache: Optional[str] = None


def find_ccache() -> Optional[str]:
    return shutil.which("ccache")


IS_WINDOWS = platform.system() == "Windows"

def _dfile_for_path(path: str, root: Optional[str]) -> str:
    if root:
        return os.path.relpath(path, root)
    return os.path.basename(path)


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
        if self.options.source_dir:
            source_root = os.path.dirname(os.path.abspath(self.options.source_dir))
            source_dir_name = os.path.basename(os.path.abspath(self.options.source_dir))
            rel_files = [os.path.join(source_dir_name, os.path.relpath(f, self.options.source_dir)) for f in files]
        else:
            source_root = os.path.dirname(os.path.abspath(files[0]))
            rel_files = [os.path.basename(f) for f in files]

        files_repr = repr(rel_files)
        source_root_repr = repr(source_root)
        content = BUILD_SCRIPT_TEMPLATE % (
            files_repr,
            source_root_repr,
            self.options.debug,
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
            ".py2dist/build_tmp",
            self.options.output_dir,
        ]:
            folder_path = os.path.join(self._work_dir, folder)
            if os.path.isdir(folder_path):
                shutil.rmtree(folder_path)

    def _clear_tmp_files(self):
        folder_path = os.path.join(self._work_dir, ".py2dist")
        if os.path.isdir(folder_path):
            shutil.rmtree(folder_path)

    def _dfile_root(self) -> Optional[str]:
        if self.options.source_dir:
            return os.path.dirname(os.path.abspath(self.options.source_dir))
        if self.options.source_file:
            return os.path.dirname(os.path.abspath(self.options.source_file))
        return None

    def _run_cython_build(self, script_path: str):
        build_dir = os.path.join(self._work_dir, ".py2dist/build")
        build_c_dir = os.path.join(self._work_dir, ".py2dist/build_c")
        build_tmp_dir = os.path.join(self._work_dir, ".py2dist/build_tmp")
        make_dirs(build_dir)
        make_dirs(build_c_dir)
        make_dirs(build_tmp_dir)

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
        cmd = f"{py_cmd} {script_path} {self._work_dir} build_ext --build-lib={build_dir} --build-temp=.py2dist/build_tmp {log} --parallel=8"

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
            src_path = os.path.join(self._work_dir, non_compile_file)
            if non_compile_file.endswith("__init__.py"):
                self._compile_init_to_pyc(src_path, dest_path)
            else:
                shutil.copyfile(src_path, dest_path)

    def _compile_init_to_pyc(self, src_path: str, dest_path: str):
        py_compile.compile(src_path, dfile=_dfile_for_path(src_path, self._dfile_root()), doraise=True)
        cache_dir = os.path.join(os.path.dirname(src_path), '__pycache__')
        base_name = os.path.splitext(os.path.basename(src_path))[0]
        if os.path.isdir(cache_dir):
            for f in os.listdir(cache_dir):
                if f.startswith(base_name) and f.endswith('.pyc'):
                    pyc_src = os.path.join(cache_dir, f)
                    pyc_dest = os.path.splitext(dest_path)[0] + '.pyc'
                    shutil.copy(pyc_src, pyc_dest)
                    os.remove(pyc_src)
                    break
            try:
                os.rmdir(cache_dir)
            except OSError:
                pass

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
    debug: bool = False,
) -> str:
    opts = CompileOptions(
        source_file=source,
        output_dir=output_dir,
        python_version=python_version,
        nthread=nthread,
        quiet=quiet,
        release=release,
        debug=debug,
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
    debug: bool = False,
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
        debug=debug,
    )
    return Compiler(opts).compile()


def compile_to_bytecode(target: str, output_dir: str, quiet: bool = False, in_place: bool = False) -> list:
    compiled_files = []
    target = os.path.abspath(target)
    output_dir = os.path.abspath(output_dir)

    if in_place:
        if os.path.isfile(target):
            if not target.endswith('.py'):
                raise ValueError("Bytecode target must be a .py file or directory")
            base_name = os.path.splitext(os.path.basename(target))[0]
            py_compile.compile(target, dfile=_dfile_for_path(target, os.path.dirname(target)), doraise=True)
            cache_dir = os.path.join(os.path.dirname(target), '__pycache__')
            if os.path.isdir(cache_dir):
                for f in os.listdir(cache_dir):
                    if f.startswith(base_name) and f.endswith('.pyc'):
                        src = os.path.join(cache_dir, f)
                        dest = os.path.join(os.path.dirname(target), base_name + '.pyc')
                        shutil.move(src, dest)
                        compiled_files.append(dest)
                        os.remove(target)
                        break
                try:
                    os.rmdir(cache_dir)
                except OSError:
                    pass
        elif os.path.isdir(target):
            success = compileall.compile_dir(
                target,
                force=True,
                quiet=2 if quiet else 0,
                stripdir=target,
                prependdir=os.path.basename(target),
            )
            if not success:
                raise RuntimeError("Bytecode compilation failed")
            for root, dirs, files in os.walk(target):
                if '__pycache__' in dirs:
                    cache_dir = os.path.join(root, '__pycache__')
                    for f in os.listdir(cache_dir):
                        if f.endswith('.pyc'):
                            src = os.path.join(cache_dir, f)
                            parts = f.rsplit('.', 2)
                            simple_name = parts[0] + '.pyc'
                            dest = os.path.join(root, simple_name)
                            shutil.move(src, dest)
                            compiled_files.append(dest)
                            py_file = os.path.join(root, parts[0] + '.py')
                            if os.path.exists(py_file):
                                os.remove(py_file)
                    try:
                        os.rmdir(cache_dir)
                    except OSError:
                        pass
        else:
            raise FileNotFoundError(f"Target not found: {target}")
    else:
        if os.path.isfile(target):
            if not target.endswith('.py'):
                raise ValueError("Bytecode target must be a .py file or directory")
            base_name = os.path.splitext(os.path.basename(target))[0]
            make_dirs(output_dir)
            py_compile.compile(target, dfile=_dfile_for_path(target, os.path.dirname(target)), doraise=True)
            cache_dir = os.path.join(os.path.dirname(target), '__pycache__')
            if os.path.isdir(cache_dir):
                for f in os.listdir(cache_dir):
                    if f.startswith(base_name) and f.endswith('.pyc'):
                        src = os.path.join(cache_dir, f)
                        dest = os.path.join(output_dir, base_name + '.pyc')
                        shutil.copy(src, dest)
                        compiled_files.append(dest)
                        os.remove(src)
                        break

        elif os.path.isdir(target):
            success = compileall.compile_dir(
                target,
                force=True,
                quiet=2 if quiet else 0,
                stripdir=target,
                prependdir=os.path.basename(target),
            )
            if not success:
                raise RuntimeError("Bytecode compilation failed")
            for root, dirs, files in os.walk(target):
                if '__pycache__' in dirs:
                    cache_dir = os.path.join(root, '__pycache__')
                    rel_root = os.path.relpath(root, target)
                    for f in os.listdir(cache_dir):
                        if f.endswith('.pyc'):
                            src = os.path.join(cache_dir, f)
                            parts = f.rsplit('.', 2)
                            simple_name = parts[0] + '.pyc'
                            if rel_root == '.':
                                dest = os.path.join(output_dir, simple_name)
                            else:
                                dest = os.path.join(output_dir, rel_root, simple_name)
                            make_dirs(os.path.dirname(dest))
                            shutil.copy(src, dest)
                            compiled_files.append(dest)
                            os.remove(src)
                    try:
                        os.rmdir(cache_dir)
                    except OSError:
                        pass
        else:
            raise FileNotFoundError(f"Target not found: {target}")

    return compiled_files
