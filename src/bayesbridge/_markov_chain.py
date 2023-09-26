#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Apr  9 15:07:01 2022

@author: fabrizio

"""

from collections import defaultdict
from copy import deepcopy
from functools import partial
import multiprocessing
import random
import math
import numpy as np
from ._log_likelihood import LogLikelihood
from ._exceptions import ForwardException, DimensionalityException


class MarkovChain:
    def __init__(self, parameterization, targets, forward_functions, temperature):
        self.parameterization = parameterization
        self.parameterization.initialize()
        self.log_likelihood = LogLikelihood(
            model=parameterization.model,
            targets=targets,
            forward_functions=forward_functions,
        )
        self._init_perturbation_funcs()
        self._init_statistics()
        self._temperature = temperature
        self._init_saved_models()
        self._init_saved_targets()

    @property
    def temperature(self):
        return self._temperature

    @temperature.setter
    def temperature(self, value):
        self._temperature = value

    @property
    def saved_models(self):
        r"""models that are saved in current chain; intialized everytime `advance_chain`
        is called

        It is a Python dict. See the following example:

        .. code-block::

           {
               'n_voronoi_cells': 5,
               'voronoi_sites': array([1.61200696, 3.69444193, 4.25564828, 4.34085936, 9.48688864]),
               'voronoi_cell_extents': array([2.65322445, 1.32182066, 0.32320872, 2.61562018, 0.        ])
           }

        """
        return getattr(self, "_saved_models", None)

    @property
    def saved_targets(self):
        """targets that are saved in current chain; intialized everytime
        `advance_chain` is called
        """
        return getattr(self, "_saved_targets", None)

    def _init_perturbation_funcs(self):
        perturb_voronoi = [self.parameterization.perturbation_voronoi_site]
        finalize_voronoi = [self.parameterization.finalize_perturbation]
        perturb_types = ["VoronoiSite"]
        if self.parameterization.trans_d:
            perturb_voronoi += [
                self.parameterization.perturbation_birth,
                self.parameterization.perturbation_death,
            ]
            finalize_voronoi += [
                self.parameterization.finalize_perturbation,
                self.parameterization.finalize_perturbation,
            ]
            perturb_types += ["Birth", "Death"]

        perturb_free_params = []
        perturb_free_params_types = []
        finalize_free_params = []
        for name in self.parameterization.free_params:
            perturb_free_params.append(
                partial(self.parameterization.perturbation_free_param, param_name=name)
            )
            perturb_free_params_types.append("Param - " + name)
            finalize_free_params.append(self.parameterization.finalize_perturbation)

        perturb_targets = []
        perturb_targets_types = []
        finalize_targets = []
        for target in self.log_likelihood.targets:
            if target.is_hierarchical:
                perturb_targets.append(target.perturb_covariance)
                perturb_targets_types.append("Target - " + target.name)
                finalize_targets.append(target.finalize_perturbation)

        self.perturbations = perturb_voronoi + perturb_free_params + perturb_targets
        self.perturbation_types = (
            perturb_types + perturb_free_params_types + perturb_targets_types
        )
        self.finalizations = finalize_voronoi + finalize_free_params + finalize_targets

        assert len(self.perturbations) == len(self.perturbation_types)
        assert len(self.perturbations) == len(self.finalizations)

    def _init_saved_models(self):
        trans_d = self.parameterization.trans_d
        saved_models = {
            k: []
            for k in self.parameterization.model.current_state
            if k != "n_voronoi_cells"
        }
        saved_models["n_voronoi_cells"] = (
            []
            if trans_d
            else self.parameterization.model.current_state["n_voronoi_cells"]
        )
        saved_models["misfits"] = []
        self._saved_models = saved_models

    def _init_saved_targets(self):
        saved_targets = {}
        for target in self.log_likelihood.targets:
            if target.save_dpred:
                saved_targets[target.name] = {"dpred": []}
            if target.is_hierarchical:
                saved_targets[target.name]["sigma"] = []
                if target.noise_is_correlated:
                    saved_targets[target.name]["correlation"] = []
        self._saved_targets = saved_targets

    def _init_statistics(self):
        self._current_misfit = float("inf")
        self._proposed_counts = defaultdict(int)
        self._accepted_counts = defaultdict(int)
        self._proposed_counts_total = 0
        self._accepted_counts_total = 0

    def _save_model(self, misfit):
        self.saved_models["misfits"].append(misfit)
        for key, value in self.parameterization.model.proposed_state.items():
            if key == "n_voronoi_cells":
                if isinstance(self.saved_models["n_voronoi_cells"], int):
                    continue
                else:
                    self.saved_models["n_voronoi_cells"].append(value)
            else:
                self.saved_models[key].append(value)

    def _save_target(self):
        for target in self.log_likelihood.targets:
            if target.save_dpred:
                self.saved_targets[target.name]["dpred"].append(
                    self.log_likelihood.proposed_dpred[target.name]
                )
            if target.is_hierarchical:
                self.saved_targets[target.name]["sigma"].append(
                    target._proposed_state["sigma"]
                )
                if target.noise_is_correlated:
                    self.saved_targets[target.name]["correlation"].append(
                        target._proposed_state["correlation"]
                    )

    def _save_statistics(self, perturb_i, accepted):
        perturb_type = self.perturbation_types[perturb_i]
        self._proposed_counts[perturb_type] += 1
        self._accepted_counts[perturb_type] += 1 if accepted else 0
        self._proposed_counts_total += 1
        self._accepted_counts_total += 1 if accepted else 0

    def _print_statistics(self):
        head = "EXPLORED MODELS: %s - " % self._proposed_counts_total
        acceptance_rate = (
            self._accepted_counts_total / self._proposed_counts_total * 100
        )
        head += "ACCEPTANCE RATE: %d/%d (%.2f %%)" % (
            self._accepted_counts_total,
            self._proposed_counts_total,
            acceptance_rate,
        )
        print(head)
        print("PARTIAL ACCEPTANCE RATES:")
        for perturb_type in sorted(self._proposed_counts):
            proposed = self._proposed_counts[perturb_type]
            accepted = self._accepted_counts[perturb_type]
            acceptance_rate = accepted / proposed * 100
            print(
                "\t%s: %d/%d (%.2f%%)"
                % (perturb_type, accepted, proposed, acceptance_rate)
            )
        print("CURRENT MISFIT: %.2f" % self._current_misfit)

    def _next_iteration(self, save_model):
        while True:
            # choose one perturbation function and type
            perturb_i = random.randint(0, len(self.perturbations) - 1)

            # propose new model and calculate probability ratios
            try:
                log_prob_ratio = self.perturbations[perturb_i]()
            except DimensionalityException:
                continue

            # calculate the forward and evaluate log_likelihood
            try:
                log_likelihood_ratio, misfit = self.log_likelihood(
                    self._current_misfit, self.temperature
                )
            except ForwardException:
                self.finalizations[perturb_i](False)
                continue

            # decide whether to accept
            accepted = log_prob_ratio + log_likelihood_ratio > math.log(random.random())

            if save_model and self.temperature == 1:
                self._save_model(misfit)
                self._save_target()

            # finalize perturbation based whether it's accepted
            self.finalizations[perturb_i](accepted)
            self._current_misfit = misfit if accepted else self._current_misfit

            # save statistics
            self._save_statistics(perturb_i, accepted)
            return

    def advance_chain(
        self,
        n_iterations=1000,
        burnin_iterations=0,
        save_every=100,
        verbose=True,
        print_every=100,
    ):
        for i in range(1, n_iterations + 1):
            if i <= burnin_iterations:
                save_model = False
            else:
                save_model = not (i - burnin_iterations) % save_every

            self._next_iteration(save_model)
            if verbose and not i % print_every:
                self._print_statistics()

        return self


class BayesianInversion:
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
        self.fwd_functions = fwd_functions
        self.n_chains = n_chains
        self.n_cpus = n_cpus
        self._chains = [
            MarkovChain(
                deepcopy(self.parameterization),
                deepcopy(self.targets),
                self.fwd_functions,
                temperature=1,
            )
            for _ in range(n_chains)
        ]

    def _init_temperatures(
        self,
        parallel_tempering=False,
        temperature_max=5,
        chains_with_unit_temperature=0.4,
    ):
        if parallel_tempering:
            temperatures = np.ones(
                max(2, int(self.n_chains * chains_with_unit_temperature)) - 1
            )
            if self.n_chains - temperatures.size > 0:
                size = self.n_chains - temperatures.size
            return np.concatenate(
                (temperatures, np.geomspace(1, temperature_max, size))
            )
        return np.ones(self.n_chains)

    @property
    def chains(self):
        return self._chains

    def run(
        self,
        n_iterations=1000,
        burnin_iterations=0,
        save_every=100,
        parallel_tempering=False,
        temperature_max=5,
        chains_with_unit_temperature=0.4,
        swap_every=500,
        verbose=True,
        print_every=100,
    ):
        temperatures = self._init_temperatures(
            parallel_tempering, temperature_max, chains_with_unit_temperature
        )

        for i, chain in enumerate(self._chains):
            chain.temperature = temperatures[i]

        partial_iterations = swap_every if parallel_tempering else n_iterations
        func = partial(
            MarkovChain.advance_chain,
            n_iterations=partial_iterations,
            burnin_iterations=burnin_iterations,
            save_every=save_every,
            verbose=verbose,
            print_every=print_every,
        )
        i_iterations = 0

        while True:
            if self.n_cpus > 1:
                pool = multiprocessing.Pool(self.n_cpus)
                self._chains = pool.map(func, self._chains)
                pool.close()
                pool.join()
            else:
                self._chains = [func(chain) for chain in self._chains]

            i_iterations += partial_iterations
            if i_iterations >= n_iterations:
                break
            if parallel_tempering:
                self.swap_temperatures()
            burnin_iterations = max(0, burnin_iterations - partial_iterations)
            func = partial(
                MarkovChain.advance_chain,
                n_iterations=partial_iterations,
                burnin_iterations=burnin_iterations,
                save_every=save_every,
                verbose=verbose,
            )

    def get_results(self, concatenate_chains=True):
        results_model = defaultdict(list)
        results_targets = {}
        for target_name in self.chains[0].saved_targets:
            results_targets[target_name] = defaultdict(list)
        for chain in self.chains:
            for key, saved_values in chain.saved_models.items():
                if concatenate_chains and isinstance(saved_values, list):
                    results_model[key].extend(saved_values)
                else:
                    results_model[key].append(saved_values)
            for target_name, target in chain.saved_targets.items():
                for key, saved_values in target.items():
                    if concatenate_chains:
                        results_targets[target_name][key].extend(saved_values)
                    else:
                        results_targets[target_name][key].append(saved_values)
        return results_model, results_targets

    def swap_temperatures(self):
        for i in range(len(self.chains)):
            chain1, chain2 = np.random.choice(self.chains, 2, replace=False)
            T1, T2 = chain1.temperature, chain2.temperature
            misfit1, misfit2 = chain1._current_misfit, chain2._current_misfit
            prob = (1 / T1 - 1 / T2) * (misfit1 - misfit2)
            if prob > math.log(random.random()):
                chain1.temperature = T2
                chain2.temperature = T1