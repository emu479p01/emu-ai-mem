class EmuMemError(RuntimeError):
    """Expected, user-actionable emu-ai-mem failure."""


class ConfigurationError(EmuMemError):
    pass


class VaultError(EmuMemError):
    pass


class SyncError(EmuMemError):
    pass


class RecordError(EmuMemError):
    pass
