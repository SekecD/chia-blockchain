from typing import Optional, List, Dict

from src.types.condition_var_pair import ConditionVarPair
from src.types.spend_bundle import SpendBundle
from src.types.coin_record import CoinRecord
from src.types.name_puzzle_condition import NPC
from src.types.program import Program
from src.full_node.mempool import Mempool
from src.types.sized_bytes import bytes32
from src.util.clvm import int_from_bytes
from src.util.condition_tools import ConditionOpcode, conditions_by_opcode
from src.util.errors import Err
import time

from src.util.ints import uint64
from src.wallet.puzzles.generator_loader import GENERATOR_MOD


def mempool_assert_coin_consumed(
    condition: ConditionVarPair, spend_bundle: SpendBundle, mempool: Mempool
) -> Optional[Err]:
    """
    Checks coin consumed conditions
    Returns None if conditions are met, if not returns the reason why it failed
    """
    bundle_removals = spend_bundle.removal_names()
    coin_name = condition.vars[0]
    if coin_name not in bundle_removals:
        return Err.ASSERT_COIN_CONSUMED_FAILED
    return None


def mempool_assert_my_coin_id(
    condition: ConditionVarPair, unspent: CoinRecord
) -> Optional[Err]:
    """
    Checks if CoinID matches the id from the condition
    """
    if unspent.coin.name() != condition.vars[0]:
        return Err.ASSERT_MY_COIN_ID_FAILED
    return None


def mempool_assert_block_index_exceeds(
    condition: ConditionVarPair, unspent: CoinRecord, mempool: Mempool
) -> Optional[Err]:
    """
    Checks if the next block index exceeds the block index from the condition
    """
    try:
        expected_block_index = int_from_bytes(condition.vars[0])
    except ValueError:
        return Err.INVALID_CONDITION
    # + 1 because min block it can be included is +1 from current
    if mempool.header.height + 1 <= expected_block_index:
        return Err.ASSERT_BLOCK_INDEX_EXCEEDS_FAILED
    return None


def mempool_assert_block_age_exceeds(
    condition: ConditionVarPair, unspent: CoinRecord, mempool: Mempool
) -> Optional[Err]:
    """
    Checks if the coin age exceeds the age from the condition
    """
    try:
        expected_block_age = int_from_bytes(condition.vars[0])
        expected_block_index = expected_block_age + unspent.confirmed_block_index
    except ValueError:
        return Err.INVALID_CONDITION
    if mempool.header.height + 1 <= expected_block_index:
        return Err.ASSERT_BLOCK_AGE_EXCEEDS_FAILED
    return None


def mempool_assert_time_exceeds(condition: ConditionVarPair):
    """
    Check if the current time in millis exceeds the time specified by condition
    """
    try:
        expected_mili_time = int_from_bytes(condition.vars[0])
    except ValueError:
        return Err.INVALID_CONDITION

    current_time = uint64(int(time.time() * 1000))
    if current_time <= expected_mili_time:
        return Err.ASSERT_TIME_EXCEEDS_FAILED
    return None


def get_name_puzzle_conditions(block_program: Program, safe_mode: bool):
    # TODO: catch failed result
    # TODO: safe mode boolean - puke on unknowns or not
    # TODO: allow generator mod to take something (future)
    # TODO: load generator_mod from hex
    cost, result = GENERATOR_MOD.run_with_cost(block_program)
    npc_list = []
    opcodes = set(item.value for item in ConditionOpcode)
    # TODO: as_python can cause blow up - use as_iter
    for res in result.as_iter():
        conditions_list = []
        name = res.first().as_atom()
        puzzle_hash = bytes32(res.rest().first().as_atom())
        for cond in res.rest().rest().first().as_iter():
            if cond.first().as_atom() in opcodes:
                opcode = ConditionOpcode(cond.first().as_atom())
            elif safe_mode:
                opcode = ConditionOpcode.UNKNOWN
            else:
                raise Exception
            # TODO: Rename CVP class
            if len(list(cond.as_iter())) > 1:
                cond_var_list = []
                for cond in cond.rest().as_iter():
                    cond_var_list.append(cond.as_atom())
                cvp = ConditionVarPair(opcode, *cond_var_list)
            else:
                cvp = ConditionVarPair(opcode)
            conditions_list.append(cvp)
        conditions_dict = conditions_by_opcode(conditions_list)
        if conditions_dict is None:
            conditions_dict = {}
        npc_list.append(NPC(name, puzzle_hash, conditions_dict))
    return None, npc_list, uint64(cost)

# TODO: write get puzzle and solution for coinname and blockprogram


def mempool_check_conditions_dict(
    unspent: CoinRecord,
    spend_bundle: SpendBundle,
    conditions_dict: Dict[ConditionOpcode, List[ConditionVarPair]],
    mempool: Mempool,
) -> Optional[Err]:
    """
    Check all conditions against current state.
    """
    for con_list in conditions_dict.values():
        cvp: ConditionVarPair
        for cvp in con_list:
            error = None
            if cvp.opcode is ConditionOpcode.ASSERT_COIN_CONSUMED:
                error = mempool_assert_coin_consumed(cvp, spend_bundle, mempool)
            elif cvp.opcode is ConditionOpcode.ASSERT_MY_COIN_ID:
                error = mempool_assert_my_coin_id(cvp, unspent)
            elif cvp.opcode is ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS:
                error = mempool_assert_block_index_exceeds(cvp, unspent, mempool)
            elif cvp.opcode is ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS:
                error = mempool_assert_block_age_exceeds(cvp, unspent, mempool)
            elif cvp.opcode is ConditionOpcode.ASSERT_TIME_EXCEEDS:
                error = mempool_assert_time_exceeds(cvp)

            if error:
                return error

    return None
