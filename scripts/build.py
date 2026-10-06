"""构建可分发版本，发布目录和ZIP均位于项目根目录。"""
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from utils.version import APP_VERSION


def main():
    release = BASE / f'Endfield_essence_v{APP_VERSION}'
    cache = BASE / 'Output' / 'build'
    release.mkdir(exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--noconsole', '--onefile',
               '--uac-admin', '--name', f'Endfield_essence_v{APP_VERSION}',
               '--icon', str(BASE/'img'/'jizhi.ico'), '--add-data', f'{BASE / "img"};img',
               '--collect-all', 'rapidocr_onnxruntime', '--collect-all', 'opencc',
               '--collect-all', 'windows_capture', '--hidden-import', 'win32timezone',
               '--workpath', str(cache/'work'), '--specpath', str(cache),
               '--distpath', str(release), str(BASE/'main.py')]
    with (cache/'build.log').open('w', encoding='utf8') as log:
        subprocess.run(command, cwd=BASE, stdout=log, stderr=subprocess.STDOUT, check=True)
    data = release/'data'
    data.mkdir(exist_ok=True)
    for name in ('weapon_data.csv', 'Jiucuo.json'):
        shutil.copy2(BASE/'data'/name, data/name)
    (release/'使用说明.txt').write_text(
        f'基质自动识别工具 v{APP_VERSION} -by洁柔厨\n\n'
        '双击exe启动，无需安装Python。请保留同目录data文件夹。\n'
        '打开游戏基质背包后开始扫描，B键停止。\n'
        '锁定基质规则可设置潜力保留条件及锁定上限。\n'
        '日志保留最近5次运行，可通过日志目录按钮查看。\n'
        '当前基质记录可查看各武器保留的词条总等级。\n'
        '本工具完全免费，群号：1006580737。\n', encoding='utf8')
    # ZIP只收入发布必需文件，排除本机运行生成的配置、记录和日志。
    import zipfile
    archive = BASE/f'Endfield_essence_v{APP_VERSION}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        for path in (release/f'Endfield_essence_v{APP_VERSION}.exe', data/'weapon_data.csv',
                     data/'Jiucuo.json', release/'使用说明.txt'):
            output.write(path, str(Path(release.name)/path.relative_to(release)))
    print(f'Release: {release}\nArchive: {archive}')


if __name__ == '__main__':
    main()
