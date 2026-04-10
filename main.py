#!/usr/bin/env python3
"""
课程助教RAG系统 - 主入口

用法:
    python main.py build [path]    # 构建知识库
    python main.py eval            # 运行评估
    python main.py test            # 运行测试
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def build_kb(args):
    """构建知识库"""
    from scripts.build_kb import main
    import sys
    sys.argv = ["build_kb"] + args
    main()


def run_eval():
    """运行检索评估"""
    from eval.retrieval import compare_methods
    compare_methods(top_k=5)


def run_tests():
    """运行单元测试"""
    import subprocess
    subprocess.run([sys.executable, "-m", "pytest", "tests/", "-v"])


def print_help():
    """打印帮助信息"""
    print("""
课程助教RAG系统

用法:
    python main.py <命令> [参数]

命令:
    build [path]    构建课程知识库 (默认: data/)
    eval            运行检索效果评估
    test            运行单元测试
    help            显示帮助信息

示例:
    python main.py build data/
    python main.py eval
    """)


def main():
    if len(sys.argv) < 2:
        print_help()
        return

    command = sys.argv[1].lower()

    if command == "build":
        build_args = sys.argv[2:] if len(sys.argv) > 2 else ["data/"]
        build_kb(build_args)
    elif command == "eval":
        run_eval()
    elif command == "test":
        run_tests()
    elif command in ("help", "-h", "--help"):
        print_help()
    else:
        print(f"未知命令: {command}")
        print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
