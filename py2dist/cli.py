import argparse
import os
import sys

from .compiler import CompileOptions, Compiler, find_ccache, get_files_in_dir, compile_to_bytecode
from . import __version__


def parse_exclude_files(value: str, root_dir: str) -> list:
    exclude = []
    root_dir_normalized = root_dir.replace('/', os.path.sep).replace('\\', os.path.sep)
    root_prefix = root_dir_normalized + os.path.sep
    for path in value.split(","):
        path = path.strip()
        if not path:
            continue
        path = path.replace('/', os.path.sep).replace('\\', os.path.sep)
        if path.startswith(root_prefix):
            path = path[len(root_prefix):]
        elif path == root_dir_normalized:
            continue
        if path.endswith(os.path.sep):
            dir_path = path.rstrip(os.path.sep)
            full_dir = os.path.join(root_dir, dir_path)
            if os.path.isdir(full_dir):
                for f in get_files_in_dir(full_dir, True, 1):
                    exclude.append(os.path.join(dir_path, f))
        else:
            exclude.append(path)
    return exclude


def get_bytecode_excludes(bytecode_target: str, source_dir: str) -> list:
    source_dir_abs = os.path.abspath(source_dir.rstrip('/\\'))
    bytecode_abs = os.path.abspath(bytecode_target)
    if not (bytecode_abs == source_dir_abs or bytecode_abs.startswith(source_dir_abs + os.path.sep)):
        return []
    if os.path.isfile(bytecode_abs):
        if not bytecode_abs.endswith(".py"):
            return []
        return [os.path.relpath(bytecode_abs, source_dir_abs)]
    if os.path.isdir(bytecode_abs):
        excludes = []
        for f in get_files_in_dir(bytecode_abs, True, 0, ".py"):
            excludes.append(os.path.relpath(f, source_dir_abs))
        return excludes
    return []


def main():
    parser = argparse.ArgumentParser(
        prog="py2dist",
        description="Compile Python files to .so/.pyd using Cython"
    )
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-f", "--file", dest="source_file", help="Single .py file to compile")
    parser.add_argument("-d", "--directory", dest="source_dir", help="Directory to compile")
    parser.add_argument("-o", "--output", dest="output_dir", default="dist", help="Output directory (default: dist)")
    parser.add_argument("-m", "--maintain", dest="exclude", default="", help="Files/dirs to exclude (comma-separated)")
    parser.add_argument("-p", "--python", dest="python_version", default="", help="Python version (e.g., 3)")
    parser.add_argument("-x", "--nthread", type=int, default=1, help="Number of parallel threads")
    parser.add_argument("-q", "--quiet", action="store_true", help="Quiet mode")
    parser.add_argument("-r", "--release", action="store_true", help="Release mode (clean tmp files)")
    parser.add_argument("-c", "--ccache", dest="ccache", nargs="?", const="auto", default=None, help="Use ccache (auto-detect or specify path)")
    parser.add_argument("-b", "--bytecode", dest="bytecode_target", help="Compile to .pyc using compileall (file or directory)")

    args = parser.parse_args()

    bytecode_target = args.bytecode_target

    if not args.source_file and not args.source_dir and not bytecode_target:
        parser.print_help()
        sys.exit(1)

    if not args.source_file and not args.source_dir:
        try:
            compiled = compile_to_bytecode(bytecode_target, args.output_dir, args.quiet)
            if not args.quiet:
                print(f"Compiled {len(compiled)} file(s) to bytecode in: {args.output_dir}")
        except Exception as e:
            print(f"Bytecode compilation error: {e}")
            sys.exit(1)
        sys.exit(0)

    if args.source_file and args.source_dir:
        print("Error: Cannot use both -f and -d")
        sys.exit(1)

    exclude_files = []
    if args.exclude and args.source_dir:
        exclude_files = parse_exclude_files(args.exclude, args.source_dir.rstrip('/'))
    if bytecode_target and args.source_dir:
        exclude_files.extend(get_bytecode_excludes(bytecode_target, args.source_dir))
        exclude_files = list(set(exclude_files))

    ccache_path = None
    if args.ccache:
        if args.ccache == "auto":
            ccache_path = find_ccache()
            if not ccache_path and not args.quiet:
                print("Warning: ccache not found, compiling without it")
        else:
            if os.path.isfile(args.ccache) and os.access(args.ccache, os.X_OK):
                ccache_path = args.ccache
            else:
                print(f"Error: ccache not found at {args.ccache}")
                sys.exit(1)

    try:
        opts = CompileOptions(
            python_version=args.python_version,
            source_file=args.source_file,
            source_dir=args.source_dir.rstrip('/') if args.source_dir else None,
            exclude_files=exclude_files,
            nthread=args.nthread,
            quiet=args.quiet,
            release=args.release,
            output_dir=args.output_dir,
            ccache=ccache_path
        )
        compiler = Compiler(opts)
        output = compiler.compile()
        if not args.quiet:
            print(f"Compiled successfully to: {output}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    if bytecode_target:
        try:
            target_in_output = None
            if args.source_dir:
                source_dir_abs = os.path.abspath(args.source_dir.rstrip('/\\'))
                bytecode_abs = os.path.abspath(bytecode_target)
                if bytecode_abs == source_dir_abs or bytecode_abs.startswith(source_dir_abs + os.path.sep):
                    rel = os.path.relpath(bytecode_abs, source_dir_abs)
                    if rel == ".":
                        target_in_output = os.path.join(args.output_dir, os.path.basename(source_dir_abs))
                    else:
                        target_in_output = os.path.join(args.output_dir, os.path.basename(source_dir_abs), rel)
            if not target_in_output:
                target_in_output = os.path.join(args.output_dir, os.path.basename(bytecode_target.rstrip('/\\')))
            if os.path.exists(target_in_output):
                compiled = compile_to_bytecode(target_in_output, args.output_dir, args.quiet, in_place=True)
            else:
                compiled = compile_to_bytecode(bytecode_target, args.output_dir, args.quiet, in_place=False)
            if not args.quiet:
                print(f"Compiled {len(compiled)} file(s) to bytecode in: {args.output_dir}")
        except Exception as e:
            print(f"Bytecode compilation error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
