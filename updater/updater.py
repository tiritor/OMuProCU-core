

import logging

from orchestrator_utils.logger.logger import init_logger


class UpdateException(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)
    

class Updater(object):
    """
    Abstract Updater class
    """
    
    def __init__(self):
        self.logger = init_logger(self.__class__.__name__, logging.INFO)
    
    def update(self):
        raise NotImplementedError