# Build with: python -m PyInstaller --noconfirm HartingDRP.spec
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
from pathlib import Path
root = Path(SPECPATH)
datas = [(str(root/'nxdrp/checkers/platform_web/frontend/dist'), 'nxdrp/checkers/platform_web/frontend/dist'),
         (str(root/'rules'), 'rules'), (str(root/'mockdata'), 'mockdata')]
datas += collect_data_files('webview')
datas += [(str(root/'nxdrp/nx_plugin'), 'nxdrp/nx_plugin')]
datas += [(str(script), 'nxdrp/journals') for script in (root/'nxdrp/journals').glob('*.py')]
datas += [(str(root/'nxdrp/checkers/performance/data'), 'nxdrp/checkers/performance/data'),
          (str(root/'nxdrp/checkers/report/knowledge.json'), 'nxdrp/checkers/report'),
          (str(root/'nxdrp/checkers/platform_web/contracts'), 'nxdrp/checkers/platform_web/contracts'),
          # 语义指令：演示页与 20 条场景用例不是 Python 模块，必须显式打包。
          (str(root/'nxdrp/assistant/demo.html'), 'nxdrp/assistant'),
          (str(root/'nxdrp/assistant/cases.json'), 'nxdrp/assistant')]
hidden = collect_submodules('nxdrp') + collect_submodules('uvicorn')
a = Analysis(['desktop.py'], pathex=[str(root)], binaries=[], datas=datas,
             hiddenimports=hidden, hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['tkinter','pytest','matplotlib','pandas','PyQt5','PyQt6','PySide2','PySide6',
                       'nxdrp.simulation.thermal','nxdrp.simulation.report'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='HartingDRP_NX',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False)
