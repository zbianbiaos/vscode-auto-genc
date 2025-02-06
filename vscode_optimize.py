#!/usr/bin/env python3
#encoding: utf-8

'''
    用于生成vscode的c_cpp_properties.json和settings.json文件
    去除所有没有参与到编译的文件和文件夹,便于vscode的代码提示和跳转
    生成的文件会放在.vscode目录下

    使用方法(该项目适用于ZephyrProject,其他项目自行移植):
        拷贝dtree.py到工程根目录下,然后执行python dtree.py <prj_dir>
        会生成.vscode/c_cpp_properties.json和.vscode/settings.json文件
    
    工作原理:
        1、os.walk遍历项目所有文件
        2、将目录结构生成DirTreeNode树
        3、解析ninja -t deps生成的deps.txt文件,得到所有参与编译的文件。如果是makefile,可以解析.d文件内容
        4、在DirTreeNode树上标记所有参与编译的文件为reserved。preserved_paths同理
        5、解析compiler_commands.json文件,得到编译器、宏定义、头文件路径、强制包含文件
        6、生成c_cpp_properties.json和settings.json文件

    实在是懒得写注释了,有问题自己看代码或者问问ChatGPT和DeepSeek吧
'''

import os
import sys
import json
import subprocess
import glob
import fnmatch

# 保留的路径，这些目录和文件即使没有参与编译也会保留
preserved_paths = [
    '.vscode',
    'class-pro'
]

# 排除的路径，因为有些文件夹内文件特别多，但这个文件夹与编译无关，生成目录树时间特别长，所以排除
discard_paths = [
    'zephyr-sdk-0.17.0',
]

# 排除的定义，有些时候会给每个文件都有一个类似NAME=XXXX，这个宏定义对于代码提示和跳转没有意义，所以排除
discard_defs = [

]

# 路径节点
class DirTreeNode:
    def __init__(self, name, parent):
        self.reserved = False # 文件树是否需要保留
        self.name = name
        self.children = []
        self.parent = parent

    # 添加子节点
    def add_child(self, child):
        self.children.append(child)
        child.parent = self

    # 设置保留标志
    def set_reserved(self):
        node = self
        while node is not None:
            node.reserved = True
            node = node.parent

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)

def __beautiful_defs(x):
    return x.replace(r'\"', r'"').replace(r'""', r'"')

def __beautiful_incs(x):
    return os.path.realpath(x)

def get_compiler_defs_incs_from_compile_commands(fname):
    with open(fname, 'r') as f:
        json_strs = f.read()
    j = json.loads(json_strs)

    compiler = None
    defs, incs, includes = [], [], []

    for x in j:
        root = x['directory']
        f = x['file']

        key = 'arguments'
        if 'command' in x:
            key = 'command'
        args = x[key]

        if type(args) is list:
            args = ' '.join(args)
        args = args.replace('-D ', '-D') \
                   .replace('-I ', '-I') \
                   .replace('-include ', '-include') \
                   .replace('-imacros ', '-imacros') \
                   .split()

        # 自动识别编译器
        if f.endswith('.c') and compiler == None:
            compiler = os.path.realpath(os.path.join(root, args[0]))
        for p in args:
            if p.startswith('-D') and len(p) > 2: defs.append(p[2:])
            if p.startswith('-I') and len(p) > 2: incs.append(p[2:])
            if p.startswith('-include') and len(p) > 8: includes.append(p[8:])
            if p.startswith('-imacros') and len(p) > 8: includes.append(p[8:])

        defs = list(set(defs))
        incs = list(set(incs))
        includes = list(set(includes))

    defs = [__beautiful_defs(x) for x in defs]
    defs = [x for x in defs if not any([x.startswith(y) for y in discard_defs])]
    defs = list(set(defs))

    incs = [__beautiful_incs(os.path.join(root, x)) for x in incs]
    incs = list(set(incs))

    includes = [__beautiful_incs(os.path.join(root, x)) for x in includes]
    includes = list(set(includes))

    defs.sort()
    incs.sort()
    includes.sort()

    return (compiler, defs, incs, includes)

def walk_root(root):
    paths = []
    for root, _, files in os.walk(root):
        for file in files:
            fname = os.path.join(root, file)
            paths.append(fname)
    return paths

def parse_deps(fname):
    with open(fname, 'r') as f:
        lines = f.readlines()
    cdeps, hdeps = [], []
    for line in lines:
        l = line.strip()
        if l.endswith('.c') or l.endswith('.cpp'):
            cdeps.append(l)
        elif l.endswith('.h') or l.endswith('.hpp'):
            hdeps.append(l)

    # 转成绝对路径
    cdeps = [os.path.realpath(x) for x in cdeps]
    hdeps = [os.path.realpath(x) for x in hdeps]

    # deps去重
    cdeps = list(set(cdeps))
    hdeps = list(set(hdeps))

    # 排序
    cdeps.sort()
    hdeps.sort()

    return cdeps + hdeps

# 将文件列表转成树
def list2tree(files):
    root = DirTreeNode('/', None)
    n = 0
    for file in files:
        n += 1
        # print(f'{n}/{len(files)}: {file}')
        path = file.split('/')
        node = root
        for p in path:
            if p == '':
                continue
            if p not in [x.name for x in node.children]:
                child = DirTreeNode(p, node)
                node.add_child(child)
                node = child
            else:
                for child in node.children:
                    if child.name == p:
                        node = child
                        break
    return root

# 标记所有files为reserved
def mark_reserved(rootNode, files):
    root = rootNode
    for file in files:
        path = file.split('/')
        node = root
        for p in path:
            if p == '':
                continue
            for child in node.children:
                if child.name == p:
                    node = child
                    break
        node.set_reserved()

# 获取节点的路径
def getNodePath(node):
    names = []
    while node is not None:
        names.append(node.name)
        node = node.parent
    return '/'.join(names[::-1]).replace('//', '/')

# 遍历树,将所有非reserved的节点加入dirs
def walk_tree(node, dirs=[]):
    if not node.reserved:
        dirs.append(getNodePath(node))
        return
    for child in node.children:
        walk_tree(child, dirs)

# 利用ninja -t deps生成deps.txt依赖文件
def gen_deps(prj):
    dbuild = os.path.join(prj, 'build')
    depname = os.path.join(dbuild, 'deps.txt')
    try:
        result = subprocess.run(f'ninja -C{dbuild} -t deps > {depname}', shell=True, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f'gen deps failed: \r\n{e.stdout}\r\n{e.stderr}')
        sys.exit(1)
    return depname

''' 
# for makefile parse .d file
def gen_deps(prj):
    dbuild = os.path.join(prj, 'build')
    depname = os.path.join(dbuild, 'deps.txt')
    dfiles = []
    for root, _, files in os.walk(dbuild):
        dfiles += [os.path.join(root, x) for x in files if x.endswith('.d')]
    dlines = []
    for f in dfiles:
        print(f)
        with open(f, 'r') as f:
            content = f.read()
        content = content.replace('\\', '').replace('\r\n', '').replace('\n', '')
        lines = content.split(' ')
        paths = [os.path.realpath(os.path.join(dbuild, x)) for x in lines if len(x) > 0 and not x.startswith('/')]
        if (len(paths) == 0):
            continue
        dlines.append(paths[0])
        dlines += ['    ' + x for x in paths[1:]]
    with open(depname, 'w') as f:
        f.write('\n'.join(dlines))
    return depname
'''

def generate_c_cpp_priorities(base, compiler, defs, incs, includes):
    j = {
        "configurations": [
            {
                "name": 'zephyr',
                "includePath": incs,
                "defines": defs,
                "compilerPath": compiler,
                "intelliSenseMode": 'linux-gcc-arm',
                "browse": {
                    "limitSymbolsToIncludedHeaders": True
                },
                "cStandard": "c99",
                "cppStandard": "c++11",
                "forcedInclude": includes
            }
        ],
        "version": 4
    }

    with open(os.path.join(base, '.vscode/c_cpp_properties.json'), 'w') as f:
        json_str = json.dumps(j, sort_keys=True, indent=4, separators=(',', ': '))
        f.write(json_str)

def generate_settings(base, epaths):
    j = {
        "files.associations": {
            "*.h": "c",
            "*_defconfig": "makefile",
            ".config*": "makefile"
        },
        "files.exclude": dict(zip(epaths, [True] * len(epaths)))
    }

    with open(os.path.join(base, '.vscode/settings.json'), 'w') as f:
        json_str = json.dumps(j, sort_keys=True, indent=4, separators=(',', ': '))
        f.write(json_str)

if __name__ == "__main__":
    if len(sys.argv)  < 2:
        print('Usage: python dtree.py <prj_dir>')
        sys.exit(1)
    
    print('init...')
    prj_dir = sys.argv[1]
    base_dir = os.path.dirname(os.path.realpath(__file__))
    prj_dir = os.path.realpath(prj_dir)
    discard_paths = [os.path.join(base_dir, x) for x in discard_paths]
    preserved_paths = [os.path.join(base_dir, x) for x in preserved_paths]
    preserved_paths = [y for x in preserved_paths for y in glob.glob(x, recursive=True)]
    preserved_paths += [file for path in preserved_paths for file in walk_root(path)]
    preserved_paths.append(os.path.realpath(__file__))
    print('preserved paths: %d' % len(preserved_paths))

    print('counting files...', end='')
    files = [file for file in walk_root(base_dir) if not any(fnmatch.fnmatch(file, pattern) for pattern in discard_paths)]
    print(len(files))

    print('gen tree...')
    root = list2tree(files)

    print('gen deps...')
    fdeps = gen_deps(prj_dir)

    print('parse deps...')
    deps = parse_deps(fdeps)
    print('dep files: %d' % len(deps))

    mark_reserved(root, deps)
    mark_reserved(root, preserved_paths)
    print('mark reserved done')

    print('filtering...', end='')
    edirs = discard_paths
    walk_tree(root, edirs)
    edirs = [os.path.relpath(x, base_dir) for x in edirs]
    edirs = ['**/.git', '**/.svn', '**/.hg', '**/CVS', '**/.DS_Store', '**/Thumbs.db'] + edirs
    print('done')

    fcmds = os.path.join(prj_dir, 'build', 'compile_commands.json')
    compiler, defs, incs, fincs = get_compiler_defs_incs_from_compile_commands(fcmds)
    compiler = os.path.realpath(compiler)
    incs = [os.path.relpath(x, base_dir) for x in incs]
    fincludes = [os.path.relpath(x, base_dir) for x in fincs]
    os.makedirs(os.path.join(base_dir, '.vscode'), exist_ok=True)
    generate_c_cpp_priorities(base_dir, compiler, defs, incs, fincludes)
    generate_settings(base_dir, edirs)
    print('generate done')
