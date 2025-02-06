# vscode-auto-genc
优化vscode开发大型C语言项目高亮和跳转小脚本

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
