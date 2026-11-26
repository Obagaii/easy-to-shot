from win32ctypes.pywin32 import pywintypes, win32cred

_DEEPSEEK_CREDENTIAL = "EasyToShot/DeepSeek"
_ERROR_NOT_FOUND = 1168


class CredentialError(RuntimeError):
    pass


def _is_valid_key(key: str) -> bool:
    return 0 < len(key) <= 512 and all(33 <= ord(character) <= 126 for character in key)


def get_deepseek_key() -> str:
    try:
        credential = win32cred.CredRead(_DEEPSEEK_CREDENTIAL, win32cred.CRED_TYPE_GENERIC)
        key = credential["CredentialBlob"].decode("utf-16-le")
    except pywintypes.error as error:
        if error.winerror == _ERROR_NOT_FOUND:
            return ""
        raise CredentialError("无法读取 Windows 凭据管理器中的 DeepSeek API Key。") from error
    except UnicodeDecodeError as error:
        raise CredentialError("无法读取已保存的 DeepSeek API Key，请重新配置。") from error
    if not _is_valid_key(key):
        raise CredentialError("已保存的 DeepSeek API Key 格式无效，请重新配置。")
    return key


def save_deepseek_key(key: str) -> None:
    key = key.strip()
    if not _is_valid_key(key):
        raise ValueError("请输入有效的 DeepSeek API Key。")
    try:
        win32cred.CredWrite({
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": _DEEPSEEK_CREDENTIAL,
            "UserName": "DeepSeek",
            "CredentialBlob": key,
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        })
    except pywintypes.error as error:
        raise CredentialError("无法将 DeepSeek API Key 保存到 Windows 凭据管理器。") from error


def delete_deepseek_key() -> None:
    try:
        win32cred.CredDelete(_DEEPSEEK_CREDENTIAL, win32cred.CRED_TYPE_GENERIC)
    except pywintypes.error as error:
        if error.winerror != _ERROR_NOT_FOUND:
            raise CredentialError("无法移除 Windows 凭据管理器中的 DeepSeek API Key。") from error
