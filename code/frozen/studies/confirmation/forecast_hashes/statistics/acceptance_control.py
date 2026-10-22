'Stop synthetic validation on failure and save partial results.'
import unittest
import sys


class CampaignStopped(RuntimeError):
    pass


class CampaignControl:
    def __init__(self,sampler,persist):
        self.sampler=sampler;self.persist=persist;self.breaches=[]
        self._stopped=False;self.result=None;self.started_test_ids=[]
        self.persistence_errors=[]

    @property
    def stopped(self):return self._stopped

    def bind(self,result):
        self.result=result
        if self.stopped:result.stop()

    def evidence(self):
        return dict(schema='AF_SCORING_RESOURCE_STOP_CHECKPOINT_V1',state='STOPPED',
                    campaign_stopped=self.stopped,breaches=list(self.breaches),
                    started_test_ids=list(self.started_test_ids),
                    tests_run=self.result.testsRun if self.result is not None else 0,
                    persistence_errors=list(self.persistence_errors),
                    synthetic_only=True,production_authority=False)

    def abort(self,exc,*,stage='resource_checkpoint'):

        first=not self.stopped;self._stopped=True
        if self.result is not None:self.result.stop()
        if first:
            self.breaches.append(dict(type=type(exc).__name__,message=str(exc),stage=stage))
            try:self.persist(self.evidence())
            except BaseException as failure:
                self.persistence_errors.append(dict(type=type(failure).__name__,message=str(failure)))
                print('AF campaign STOPPED: '+str(exc)+'; checkpoint write failed: '+str(failure),file=sys.stderr,flush=True)
        return self.breaches[0]

    def checkpoint(self,*_):
        if self.stopped:
            if self.result is not None:self.result.stop()
            raise CampaignStopped('Campaign remains stopped: '+self.breaches[0]['message'])
        try:return self.sampler()
        except BaseException as exc:
            reason=self.abort(exc)
            raise CampaignStopped('Resource checkpoint stopped campaign: '+reason['message']) from exc


def result_class(control):

    class StoppingResult(unittest.TextTestResult):
        def startTest(self,test):
            control.checkpoint()
            control.started_test_ids.append(test.id())
            super().startTest(test)
        def stopTest(self,test):
            super().stopTest(test)
            if control.stopped:
                self.stop()
                return
            control.checkpoint()
    return StoppingResult
