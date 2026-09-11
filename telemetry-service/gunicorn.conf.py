import os

chdir = "/app/src"
bind = "0.0.0.0:30600"
workers = 1  # one UDP socket per pod
threads = 8
accesslog = "-"


def post_worker_init(worker):
    from app import start_log_receiver
    worker.log_receiver = start_log_receiver(int(os.getenv("LOG_PORT", "9000")))


def worker_exit(server, worker):
    if hasattr(worker, "log_receiver"):
        worker.log_receiver.shutdown()
        worker.log_receiver.server_close()
