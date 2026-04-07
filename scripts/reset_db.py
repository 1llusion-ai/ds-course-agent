import os
import shutil
import utils.config as config

if os.path.exists(config.persist_directory):
    shutil.rmtree(config.persist_directory)

if os.path.exists(config.md5_path):
    os.remove(config.md5_path)

os.makedirs(config.persist_directory, exist_ok=True)
print("知识库已清空")