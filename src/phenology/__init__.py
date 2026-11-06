"""
src/phenology
=============
Neural-Phenology Modeling Package for Protected Greenhouse Crops.

Provides:
- SmoothChillingGate: Dynamical low-temperature dormancy soft gate with state-space memory
- SmoothThermalKernel: C^inf continuous Softplus-Sigmoidal thermal time kernel
- MultiFactorSensoryFusion: Microclimate sensory fusion (Tavg, DIF MLP, light limitation)
- NeuralPhenologyOperator: Master neural phenology operator with strictly monotonic D(t)
- PhenologyLoss: Bounded differentiable loss with soft milestone prediction & curvature penalty
- load_benchmark_dataset, get_seasonal_tensor_bundle: Relational benchmark loaders
"""

from src.phenology.dataset import (
    load_benchmark_dataset,
    get_seasonal_tensor_bundle,
)
from src.phenology.chilling_gate import (
    SmoothChillingGate,
)
from src.phenology.operator import (
    SmoothThermalKernel,
    MultiFactorSensoryFusion,
    NeuralPhenologyOperator,
)
from src.phenology.loss import (
    PhenologyLoss,
    DEFAULT_STAGE_ANCHORS,
)

__all__ = [
    "load_benchmark_dataset",
    "get_seasonal_tensor_bundle",
    "SmoothChillingGate",
    "SmoothThermalKernel",
    "MultiFactorSensoryFusion",
    "NeuralPhenologyOperator",
    "PhenologyLoss",
    "DEFAULT_STAGE_ANCHORS",
]
