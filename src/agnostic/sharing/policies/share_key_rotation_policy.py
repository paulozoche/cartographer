from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ShareSigningKey:
    key_id: str
    secret: str
    can_sign: bool = False
    can_verify: bool = True


def validate_share_signing_keys(keys: list[ShareSigningKey]) -> None:
    if not keys:
        raise ValueError("É necessário definir ao menos uma chave de assinatura.")
    seen: set[str] = set()
    for key in keys:
        key_id = key.key_id.strip()
        secret = key.secret.strip()
        if not key_id:
            raise ValueError("key_id de assinatura não pode ser vazio.")
        if key_id in seen:
            raise ValueError(f"key_id duplicado na configuração de rotação: {key_id}")
        seen.add(key_id)
        if len(secret) < 8:
            raise ValueError(f"Segredo da chave '{key_id}' deve ter no mínimo 8 caracteres.")


def resolve_signing_key(
    keys: list[ShareSigningKey],
    *,
    preferred_key_id: str | None = None,
) -> ShareSigningKey:
    validate_share_signing_keys(keys)
    if preferred_key_id:
        for key in keys:
            if key.key_id == preferred_key_id and key.can_sign:
                return key
        raise ValueError(f"Chave preferida '{preferred_key_id}' não está apta para assinatura.")

    sign_candidates = [key for key in keys if key.can_sign]
    if len(sign_candidates) != 1:
        raise ValueError("A rotação deve ter exatamente uma chave apta para assinatura ativa.")
    return sign_candidates[0]


def build_verification_keyring(keys: list[ShareSigningKey]) -> dict[str, str]:
    validate_share_signing_keys(keys)
    return {key.key_id: key.secret for key in keys if key.can_verify}
