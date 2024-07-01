# -*- coding: utf-8 -*-
import base64
from typing import Any, Dict, Optional, Union

import nacl.signing
import requests
from pydantic import BaseModel
from solana.rpc.async_api import AsyncClient
from solana.transaction import Transaction
from solders.pubkey import Pubkey


class FetchActionError(Exception):
    pass


class SerializeTransactionError(Exception):
    pass


class ActionPostRequest(BaseModel):
    account: str


class ActionPostResponse(BaseModel):
    transaction: str
    message: Optional[str] = None


class ActionPostResponseWithSerializedTransaction(ActionPostResponse):
    transaction: Transaction


async def fetch_transaction(
    connection: AsyncClient,
    link: str,
    fields: ActionPostRequest,
    options: Dict[str, Any] = {},
) -> ActionPostResponseWithSerializedTransaction:
    response = requests.post(
        str(link),
        json=fields.dict(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=5,
    )
    json_data = response.json()

    if not json_data.get("transaction"):
        raise FetchActionError("missing transaction")
    if not isinstance(json_data["transaction"], str):
        raise FetchActionError("invalid transaction")

    transaction = await serialize_transaction(
        connection, fields.account, json_data["transaction"], options
    )

    return ActionPostResponseWithSerializedTransaction(
        **json_data, transaction=transaction
    )


async def serialize_transaction(
    connection: AsyncClient,
    account: Union[str, Pubkey],
    base64_transaction: str,
    options: Dict[str, Any] = {},
) -> Transaction:
    if isinstance(account, str):
        account = Pubkey(account)

    transaction = Transaction.deserialize(base64.b64decode(base64_transaction))
    signatures = transaction.signatures
    fee_payer = transaction.fee_payer()
    recent_blockhash = transaction.recent_blockhash

    if signatures:
        if not fee_payer:
            raise SerializeTransactionError("missing fee payer")
        if fee_payer != signatures[0].pubkey:
            raise SerializeTransactionError("invalid fee payer")
        if not recent_blockhash:
            raise SerializeTransactionError("missing recent blockhash")

        message = transaction.serialize_message()
        for sig in signatures:
            if sig.signature:
                if not nacl.signing.VerifyKey(bytes(sig.pubkey)).verify(
                    message, sig.signature
                ):
                    raise SerializeTransactionError("invalid signature")
            elif sig.pubkey == account:
                if len(signatures) == 1:
                    transaction.recent_blockhash = (
                        await connection.get_recent_blockhash(
                            commitment=options.get("commitment")
                        )
                    ).value.blockhash
            else:
                raise SerializeTransactionError("missing signature")
    else:
        transaction.fee_payer = account
        transaction.recent_blockhash = (
            await connection.get_recent_blockhash(commitment=options.get("commitment"))
        ).value.blockhash

    return transaction
