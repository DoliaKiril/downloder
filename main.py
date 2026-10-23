import flet as ft
import threading
import requests
import os
import time
from urllib.parse import unquote, urlparse

# Папка Download на твоем Z Flip 7 FE
DOWNLOAD_DIR = "/storage/emulated/0/Download"
MAX_CONCURRENT = 3 # Максимум потоков, чтобы избежать IP-бана от Cloudflare

class DownloaderApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "Kemono Aggressive DL"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.padding = 0

        self.tasks = []
        self.active_downloads = 0
        self.lock = threading.Lock()

        # Попытка создать папку, если ее нет
        try:
            os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        except Exception:
            pass 

        # Интерфейс
        self.url_input = ft.TextField(label="Вставь ссылку на файл", expand=True)
        self.add_btn = ft.ElevatedButton("Добавить", on_click=self.add_url, bgcolor="blue")

        self.active_list = ft.ListView(expand=True, spacing=10, padding=10)
        self.done_list = ft.ListView(expand=True, spacing=10, padding=10)
        self.failed_list = ft.ListView(expand=True, spacing=10, padding=10) 

        self.tabs = ft.Tabs(
            selected_index=0,
            animation_duration=300,
            expand=True,
            tabs=[
                ft.Tab(text="Загрузки", content=self.active_list),
                ft.Tab(text="Готово", content=self.done_list),
                ft.Tab(text="Ошибки", content=self.failed_list), # Сюда ничего не попадет, скрипт бессмертный
            ],
        )

        top_row = ft.Container(
            content=ft.Row([self.url_input, self.add_btn]),
            padding=10
        )
        self.page.add(top_row, self.tabs)

        # Фоновый поток для обновления UI
        threading.Thread(target=self.ui_updater, daemon=True).start()

    def ui_updater(self):
        while True:
            time.sleep(1)
            with self.lock:
                self.page.update()

    def add_url(self, e):
        url = self.url_input.value.strip()
        if not url: return
        self.url_input.value = ""
        self.page.update()

        filename = os.path.basename(urlparse(url).path)
        if not filename:
            filename = f"file_{int(time.time())}.bin"
        filename = unquote(filename)

        task = {
            "url": url,
            "filename": filename,
            "progress": 0.0,
            "status": "queued", 
            "size_str": "Подключение...",
        }

        # Блок задачи в UI
        progress_bar = ft.ProgressBar(value=0, color="amber", bgcolor="#333333")
        text_info = ft.Text(f"{filename}\nВ очереди...", size=14)
        task["ui"] = ft.Container(
            content=ft.Column([text_info, progress_bar]),
            padding=15,
            bgcolor="#1A1A1A",
            border_radius=10
        )

        with self.lock:
            self.tasks.append(task)
            self.active_list.controls.append(task["ui"])

        threading.Thread(target=self.process_queue, daemon=True).start()

    def process_queue(self):
        with self.lock:
            if self.active_downloads >= MAX_CONCURRENT:
                return
            task = next((t for t in self.tasks if t["status"] == "queued"), None)
            if not task:
                return
            task["status"] = "downloading"
            self.active_downloads += 1

        self.download_file(task)

        with self.lock:
            self.active_downloads -= 1
            if task["status"] == "done":
                self.active_list.controls.remove(task["ui"])
                self.done_list.controls.append(task["ui"])

        # Запуск следующей задачи из очереди
        threading.Thread(target=self.process_queue, daemon=True).start()

    def download_file(self, task):
        filepath = os.path.join(DOWNLOAD_DIR, task["filename"])
        session = requests.Session()
        
        # Маскируемся под обычный браузер
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
            "Referer": "https://kemono.su/"
        })

        while True:
            downloaded = os.path.getsize(filepath) if os.path.exists(filepath) else 0
            headers = {"Range": f"bytes={downloaded}-"} if downloaded > 0 else {}

            try:
                # Таймаут 15с на коннект, 60с на чтение. Если виснет - рвем и переподключаемся
                with session.get(task["url"], headers=headers, stream=True, timeout=(15, 60)) as r:
                    if r.status_code == 416: # 416 = файл уже полностью скачан
                        task["progress"] = 1.0
                        task["status"] = "done"
                        self.update_task_ui(task, f"{task['filename']}\nУспешно скачан!")
                        break

                    if r.status_code not in (200, 206):
                        time.sleep(3) # Ждем 3 сек при ошибке сервера и долбим снова
                        continue

                    total_size = int(r.headers.get('content-length', 0)) + downloaded
                    total_mb = total_size / (1024 * 1024)

                    with open(filepath, 'ab') as f:
                        for chunk in r.iter_content(chunk_size=128 * 1024): # Читаем кусками по 128 КБ
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total_size > 0:
                                    task["progress"] = downloaded / total_size
                                    dl_mb = downloaded / (1024 * 1024)
                                    task["size_str"] = f"{dl_mb:.1f} MB / {total_mb:.1f} MB"
                                    pct = task['progress'] * 100
                                    self.update_task_ui(task, f"{task['filename']}\n{task['size_str']} ({pct:.1f}%)")

                    # Если вышли из цикла чтения без ошибок - готово
                    task["progress"] = 1.0
                    task["status"] = "done"
                    self.update_task_ui(task, f"{task['filename']}\nУспешно скачан!")
                    break

            except Exception as e:
                # Обрыв соединения. Никакой паники, спим 3 секунды и качаем с места обрыва
                time.sleep(3)
                continue

    def update_task_ui(self, task, text):
        col = task["ui"].content
        col.controls[0].value = text
        col.controls[1].value = task["progress"]

def main(page: ft.Page):
    DownloaderApp(page)

ft.app(target=main)
