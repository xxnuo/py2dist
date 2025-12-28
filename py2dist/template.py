BUILD_SCRIPT_TEMPLATE = r'''import os
import sys
from setuptools import Extension, setup
from Cython.Build import cythonize
from Cython.Distutils import build_ext

work_dir = sys.argv[1]
sys.argv = [sys.argv[0]] + sys.argv[2:]

extensions = []
rel_filenames = %s
source_root = %s

old_cwd = os.getcwd()
os.chdir(source_root)

for rel_filename in rel_filenames:
    mod_name = rel_filename[:-3].replace(os.path.sep, '.')
    extension = Extension(mod_name, [rel_filename])
    extension.cython_c_in_temp = True
    extensions.append(extension)

py_ver = '%s'
if py_ver == '':
    py_ver = '3'
compiler_directives = {"language_level": py_ver, "annotation_typing": False}

setup(
    cmdclass={'build_ext': build_ext},
    packages=[],
    zip_safe=False,
    ext_modules=cythonize(
        extensions,
        nthreads=%s,
        build_dir=".py2dist/build_c",
        quiet=%s,
        compiler_directives=compiler_directives
    )
)

os.chdir(old_cwd)
'''
