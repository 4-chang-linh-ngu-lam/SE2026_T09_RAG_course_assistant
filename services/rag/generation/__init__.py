"""Local generation adapters and answer-contract validation."""

from .vi_mrc_reader import VI_MRC_ANSWER_VERSION, VI_MRC_READER_VERSION, ViMrcReader
from .rag_generation import BudgetOnlyGenerator

__all__ = ["BudgetOnlyGenerator", "VI_MRC_ANSWER_VERSION", "VI_MRC_READER_VERSION", "ViMrcReader"]
