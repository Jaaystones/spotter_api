import logging

from django.core.management.commands.runserver import Command as RunserverCommand

logger = logging.getLogger(__name__)


class Command(RunserverCommand):
    def on_bind(self, server_port):
        if self._raw_ipv6:
            addr = f'[{self.addr}]'
        elif self.addr == '0':
            addr = '0.0.0.0'
        else:
            addr = self.addr

        logger.info('Starting development server at %s://%s:%s/', self.protocol, addr, server_port)
