import logging, signal, time
from apscheduler.schedulers.blocking import BlockingScheduler
from .config import Settings
from .logging_config import setup_logging
from .change_detector import ChangeDetector

log=logging.getLogger(__name__)
def main():
    s=Settings.from_env(); setup_logging(s.log_dir); d=ChangeDetector(s); sched=BlockingScheduler(timezone='UTC')
    def job():
        try: d.run_once()
        except Exception: log.exception('Scheduled cycle failed; scheduler remains alive')
    sched.add_job(job,'interval',hours=s.check_interval_hours,id='bis-change-detector',max_instances=1,coalesce=True,next_run_time=None)
    def stop(*_): log.info('Graceful shutdown requested'); sched.shutdown(wait=False)
    signal.signal(signal.SIGINT,stop); signal.signal(signal.SIGTERM,stop)
    log.info('BIS Change Detector started; interval=%sh',s.check_interval_hours)
    job(); sched.start()
if __name__=='__main__': main()
