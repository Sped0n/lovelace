# custom exception
class CmdTypeError(Exception):
    pass


class CmdContentError(Exception):
    pass


class PacketCorruptError(Exception):
    pass


class NoConnectionError(Exception):
    pass
