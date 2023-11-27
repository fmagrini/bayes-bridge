from typing import List, Callable, Tuple, Any, Dict
from numbers import Number
from copy import deepcopy
from collections import defaultdict

from ._markov_chain import MarkovChain, BaseMarkovChain
from .samplers import VanillaSampler


class BaseBayesianInversion:
    def __init__(
        self,
        walkers_starting_models: List[Any],
        perturbation_funcs: List[Callable[[Any], Tuple[Any, Number]]],
        log_prior_func: Callable[[Any], Number],
        log_likelihood_func: Callable[[Any], Number],
        n_chains: int = 10,
        n_cpus: int = 10,
    ):
        self.walkers_starting_models = walkers_starting_models
        self.perturbation_funcs = [
            _preprocess_func(func) for func in perturbation_funcs
        ]
        self.log_prior_func = _preprocess_func(log_prior_func)
        self.log_likelihood_func = _preprocess_func(log_likelihood_func)
        self.n_chains = n_chains
        self.n_cpus = n_cpus
        self._chains = [
            BaseMarkovChain(
                i,
                walkers_starting_models[i],
                perturbation_funcs,
                self.log_prior_func,
                self.log_likelihood_func,
            )
            for i in range(n_chains)
        ]

    @property
    def chains(self) -> List[BaseMarkovChain]:
        return self._chains

    def run(
        self,
        sampler=None,
        n_iterations=1000,
        burnin_iterations=0,
        save_every=100,
        verbose=True,
        print_every=100,
    ):
        if sampler is None:
            sampler = VanillaSampler()
        sampler.initialize(self.chains)
        self._chains = sampler.run(
            n_iterations=n_iterations,
            n_cpus=self.n_cpus,
            burnin_iterations=burnin_iterations,
            save_every=save_every,
            verbose=verbose,
            print_every=print_every,
        )

    def get_results(self, concatenate_chains=True) -> Dict[str, list]:
        results_model = defaultdict(list)
        for chain in self.chains:
            for key, saved_values in chain.saved_models.items():
                if concatenate_chains and isinstance(saved_values, list):
                    results_model[key].extend(saved_values)
                else:
                    results_model[key].append(saved_values)
        return results_model


class BayesianInversion(BaseBayesianInversion):
    def __init__(
        self,
        parameterization,
        targets,
        fwd_functions,
        n_chains=10,
        n_cpus=10,
    ):
        self.parameterization = parameterization
        self.targets = targets
        self.fwd_functions = [_preprocess_func(func) for func in fwd_functions]
        self.n_chains = n_chains
        self.n_cpus = n_cpus
        self._chains = [
            MarkovChain(
                i,
                deepcopy(self.parameterization),
                deepcopy(self.targets),
                self.fwd_functions,
            )
            for i in range(n_chains)
        ]


def _preprocess_func(func):
    f = None
    args = []
    kwargs = {}
    if isinstance(func, (tuple, list)) and len(func) > 1:
        f = func[0]
        if isinstance(func[1], (tuple, list)):
            args = func[1]
            if len(func) > 2 and isinstance(func[2], dict):
                kwargs = func[2]
        elif isinstance(func[1], dict):
            kwargs = func[1]
    elif isinstance(func, (tuple, list)):
        f = func[0]
    else:
        f = func
    return _FunctionWrapper(f, args, kwargs)


class _FunctionWrapper(object):
    """Function wrapper to make it pickleable (credit to emcee)"""

    def __init__(self, f, args, kwargs):
        self.f = f
        self.args = args or []
        self.kwargs = kwargs or {}

    def __call__(self, x):
        return self.f(x, *self.args, **self.kwargs)
