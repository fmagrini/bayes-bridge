#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Dec 21 15:56:00 2022

@author: fabrizio
"""

import random
from functools import partial
from copy import copy, deepcopy
import math
from math import pi, sqrt, log
from collections import Iterable
import numpy as np
from _utils_bayes import interpolate_linear_1d, nearest_index
from _utils_bayes import _get_thickness, _is_sorted


TWO_PI = 2 * math.pi
SQRT_TWO_PI = math.sqrt(TWO_PI)

class Model:
    
    def __init__(self, n_voronoi_cells, voronoi_sites):
        self.n_voronoi_cells = n_voronoi_cells
        self.voronoi_sites = voronoi_sites
        self.voronoi_cell_extents = \
            self._get_voronoi_cell_extents(self.voronoi_sites)
        self.current_state = self._init_current_state()
        self.proposed_state = deepcopy(self.current_state)
        self._current_perturbation = {}
        self._finalize_dict = dict(
            site=self._finalize_site_perturbation,
            free_param=self._finalize_free_param_perturbation, 
            birth=self._finalize_birth_death_perturbation, 
            death=self._finalize_birth_death_perturbation, 
        )


    @property
    def current_perturbation(self):
        return self._current_perturbation
    
    
    def _init_current_state(self):
        current_state = {}
        current_state['n_voronoi_cells'] = self.n_voronoi_cells
        current_state['voronoi_sites'] = self.voronoi_sites
        current_state['voronoi_cell_extents'] = self.voronoi_cell_extents
        return current_state
    
    
    def _get_voronoi_cell_extents(self, voronoi_sites):
        return _get_thickness(voronoi_sites)
    
    
    def add_free_parameter(self, name, values):
        self.current_state[name] = values
        self.proposed_state[name] = values.copy()

        
    def propose_site_perturbation(self, isite, site):
        self.proposed_state['voronoi_sites'][isite] = site
        self._sort_proposed_state()
        self._current_perturbation['type'] = 'site'

    
    def propose_free_param_perturbation(self, name, idx, value):
        self.proposed_state[name][idx] = value
        self._current_perturbation['type'] = name
        self._current_perturbation['idx'] = idx
                
    
    def propose_birth_perturbation(self):
        self.proposed_state['n_voronoi_cells'] += 1
        self._sort_proposed_state()
        self._current_perturbation['type'] = 'birth'
        
        
    def propose_death_perturbation(self, ):
        self.proposed_state['n_voronoi_cells'] -= 1
        self.proposed_state['voronoi_cell_extents'] = \
            self._get_voronoi_cell_extents(
                self.proposed_state['voronoi_sites']        
                )
        self._current_perturbation['type'] = 'death'
        
    
    def finalize_perturbation(self, accepted):
        perturb_type = self._current_perturbation['type']
        if perturb_type in self._finalize_dict:
            finalize = self._finalize_dict[perturb_type]
        else:
            finalize = self._finalize_dict['free_param']
        accepted_state = self.proposed_state if accepted else self.current_state
        rejected_state = self.current_state if accepted else self.proposed_state
        finalize(accepted_state, rejected_state)
    
    
    def _finalize_site_perturbation(self, accepted_state, rejected_state):
        rejected_state['voronoi_sites'] = accepted_state['voronoi_sites'].copy()
        rejected_state['voronoi_cell_extents'] = \
            accepted_state['voronoi_cell_extents'].copy()
        
    
    def _finalize_free_param_perturbation(self, accepted_state, rejected_state):
        name = self._current_perturbation['type']
        idx = self._current_perturbation['idx']
        rejected_state[name][idx] = accepted_state[name][idx]
    
    
    def _finalize_birth_death_perturbation(self, accepted_state, rejected_state):
        for k, v in accepted_state.items():
            if isinstance(v, int):
                rejected_state[k] = v
            else:
                rejected_state[k] = v.copy()
            
            
    def _sort_proposed_state(self):
        isort = np.argsort(self.proposed_state['voronoi_sites'])
        if not _is_sorted(isort):
            for key in self.proposed_state:
                if not key in ['n_voronoi_cells', 'voronoi_cell_extents']:
                    self.proposed_state[key] = self.proposed_state[key][isort]
            
        self.proposed_state['voronoi_cell_extents'] = \
            self._get_voronoi_cell_extents(
                self.proposed_state['voronoi_sites']        
                )
        


class Parameterization:
        
    def perturbation_birth(self):
        raise NotImplementedError
        
    def perturbation_death(self):
        raise NotImplementedError
        
    def perturbation_voronoi_site(self):
        raise NotImplementedError
        
    def perturbation_free_param(self):
        raise NotImplementedError
        
    def finalize_perturbation(self):
        raise NotImplementedError
    


class Parameterization1D(Parameterization):
    
    def __init__(self, 
                 n_voronoi_cells, 
                 voronoi_site_bounds,
                 voronoi_site_perturb_std,
                 free_params=None,
                 trans_d=False, 
                 n_voronoi_cells_min=None, 
                 n_voronoi_cells_max=None):        
        
        self.n_voronoi_cells = n_voronoi_cells
        self.voronoi_site_bounds = voronoi_site_bounds
        self._voronoi_site_perturb_std = \
            self._init_voronoi_site_perturb_std(voronoi_site_perturb_std)
                   
        self.trans_d = trans_d
        if trans_d:
            self.n_voronoi_cells_min = n_voronoi_cells_min
            self.n_voronoi_cells_max = n_voronoi_cells_max
        self.voronoi_sites = self._init_voronoi_sites()
            
        self.model = Model(self.n_voronoi_cells, self.voronoi_sites)
            
        self.free_params = {}
        if free_params is not None:
            for param in free_params:
                self.add_free_parameter(param)

            
    def add_free_parameter(self, free_param):
        self.free_params[free_param.name] = free_param
        values = free_param.generate_random_values(self.voronoi_sites, 
                                                   is_init=True)
        self.model.add_free_parameter(free_param.name, values)

        
    def _init_voronoi_sites(self):
        lb, ub = self.voronoi_site_bounds
        return np.sort(np.random.uniform(lb, ub, self.n_voronoi_cells))
               
        
    def _init_voronoi_site_perturb_std(self, std):
        if np.isscalar(std):
            return std
        std = np.array(std, dtype=float)
        return partial(interpolate_linear_1d, x=std[:,0], y=std[:,1]) 


    def get_voronoi_site_perturb_std(self, site):
        if np.isscalar(self._voronoi_site_perturb_std):
            return self._voronoi_site_perturb_std
        return self._voronoi_site_perturb_std(site)
    
    
    def perturbation_birth(self):
        old_sites = self.model.proposed_state['voronoi_sites']
        while True:
            lb, ub = self.voronoi_site_bounds
            new_site = random.uniform(lb, ub)
            if np.any(np.abs(new_site - old_sites) < 1e-2):
                continue
            break
        
        self.model.proposed_state['voronoi_sites'] = \
            np.append(old_sites, new_site)
            
        isite = nearest_index(xp=new_site, 
                              x=old_sites, 
                              xlen=old_sites.size)
        prob_ratio = 0
        for param_name, param in self.free_params.items():
            old_values = self.model.current_state[param_name]
            old_value = old_values[isite]
            
            new_value = param.perturb_value(new_site, 
                                            old_value)
            prob_ratio += self.probability_ratio_birth_death_perturbation(
                param, new_site, old_value, new_value
                )
            self.model.proposed_state[param_name] = \
                np.append(old_values, new_value)
 
        self.model.propose_birth_perturbation()
        return prob_ratio
        
            
        
    def perturbation_death(self):
        n_cells = self.model.current_state['n_voronoi_cells']
        isite = random.randint(0, n_cells-1)
        site_to_remove = self.model.current_state['voronoi_sites'][isite]
        old_sites = self.model.current_state['voronoi_sites']
        new_sites = np.delete(old_sites, isite)
        self.model.proposed_state['voronoi_sites'] = new_sites
        
        iclosest = nearest_index(xp=site_to_remove, 
                                 x=new_sites, 
                                 xlen=new_sites.size)
        prob_ratio = 0
        for param_name, param in self.free_params.items():
            old_values = self.model.current_state[param_name]
            new_values = np.delete(old_values, isite)
            self.model.proposed_state[param_name] = new_values
            old_value = old_values[isite]
            new_value = new_values[iclosest]
            
            prob_ratio -= self.probability_ratio_birth_death_perturbation(
                param, site_to_remove, old_value, new_value
                )
 
        self.model.propose_death_perturbation()
        return prob_ratio

    
    
    def perturbation_voronoi_site(self):
        isite = random.randint(0, self.n_voronoi_cells-1)
        old_site = self.voronoi_sites[isite]
        site_min, site_max = self.voronoi_site_bounds
        std = self.get_voronoi_site_perturb_std(old_site)
        
        while True:
            random_deviate = random.normalvariate(0, std)
            new_site = old_site + random_deviate
            if new_site<site_min or new_site>site_max: 
                continue
            if np.any(np.abs(new_site - self.voronoi_sites) < 1e-2):
                continue
            break
        self.model.propose_site_perturbation(isite, new_site)
        return self.probability_ratio_site_perturbation(old_site, new_site)


    def perturbation_free_param(self, param_name):
        isite = random.randint(0, self.n_voronoi_cells-1)
        site = self.voronoi_sites[isite]
        old_value = self.model.current_state[param_name][isite]
        new_value = self.free_params[param_name].perturb_value(site, old_value)
        self.model.propose_free_param_perturbation(param_name, isite, new_value)
        return self.probability_ratio_free_param_perturbation(param_name)
        

    def finalize_perturbation(self, accepted):
        self.model.finalize_perturbation(accepted)


    def probability_ratio_birth_death_perturbation(self, 
                                                   param,
                                                   perturbed_site, 
                                                   value, 
                                                   perturbed_value):
        """
        Returns probability ratio associated with a single free parameter
        """
        std_perturb = param.get_perturb_std(perturbed_site)
        delta = param.get_delta(perturbed_site)
        term1 = math.log(SQRT_TWO_PI * std_perturb / delta)
        term2 = (perturbed_value - value)**2 / (2 * std_perturb**2)
        return term1 + term2
        

    def probability_ratio_site_perturbation(self, old_site, new_site):
        proposal_ratio = self._proposal_ratio_site_perturbation(old_site, 
                                                                new_site)
        prior_ratio = self._prior_ratio_site_perturbation(old_site, new_site)
        return proposal_ratio + prior_ratio     


    def probability_ratio_free_param_perturbation(self, param_name):
        param = self.free_params[param_name]
        prior_ratio = param.prior_ratio_value_perturbation()
        proposal_ratio = param.proposal_ratio_value_perturbation()
        return prior_ratio + proposal_ratio

    
    def _proposal_ratio_site_perturbation(self, old_site, new_site):
        std_old = self.get_voronoi_site_perturb_std(old_site)
        std_new = self.get_voronoi_site_perturb_std(new_site)
        d = (old_site - new_site)**2
        term1 = math.log(std_old/std_new)
        term2 = d * (std_new**2 - std_old**2) / (2 * std_new**2 * std_old**2)
        return term1 + term2
    
    
    def _prior_ratio_site_perturbation(self, old_site, new_site):
        prob_ratio = 0
        for param in self.free_params.values():
            prob_ratio += \
                param.prior_ratio_position_perturbation(old_site, new_site)
        return prob_ratio



class Parameter:
    
    def get_perturb_std(self, position):
        raise NotImplementedError  
    
    
    def generate_random_value(self, position):
        raise NotImplementedError
    
    
    def perturb_value(self, position, value):
        raise NotImplementedError
    
    
    def prior_probability(self, old_position, new_position):
        raise NotImplementedError
    
    
    def proposal_probability(self, 
                             old_position, 
                             old_value, 
                             new_position, 
                             new_value):
        raise NotImplementedError

        
    
class PositionDependendentUniformParam(Parameter):
    
    def __init__(self, name, position, vmin, vmax, perturb_std, init_sorted=False):
        self.init_params = {'name': name,
                            'position': position,
                            'vmin': vmin,
                            'vmax': vmax,
                            'perturb_std': perturb_std,
                            'init_sorted': init_sorted}
        self.name = name
        self.position = np.array(position, dtype=float)
        self._vmin, self._vmax = self._init_vmin_vmax(vmin, vmax)
        self._delta = self._init_delta(vmin, vmax) # Either a scalar or interpolator
        self._perturb_std = self._init_perturb_std(perturb_std)
        self.init_sorted = init_sorted
        
        
    
    def __repr__(self):
        string = '%s('%self.init_params['name']
        for k, v in self.init_params.items():
            if k == 'name':
                continue
            string += '%s=%s, '%(k, v)
        string = string[:-2]
        return string + ')'
    
    
    def _init_vmin_vmax(self, vmin, vmax):
        if np.isscalar(vmin) and np.isscalar(vmax):
            return vmin, vmax
        if not np.isscalar(vmin):
            vmin = np.array(vmin, dtype=float)
            vmin = np.full(self.position.size, vmin) if np.isscalar(vmin) else vmin
            vmin = partial(interpolate_linear_1d, x=self.position, y=vmin)
        if not np.isscalar(vmax):
            vmax = np.array(vmax, dtype=float)
            vmax = np.full(self.position.size, vmax) if np.isscalar(vmax) else vmax
            vmax = partial(interpolate_linear_1d, x=self.position, y=vmax)
        return vmin, vmax
        
    
    def _init_delta(self, vmin, vmax):
        delta = np.array(vmax, dtype=float) - np.array(vmin, dtype=float)
        if np.isscalar(delta):
            return delta
        return partial(interpolate_linear_1d, x=self.position, y=delta) 
    
    
    def _init_perturb_std(self, perturb_std):
        if np.isscalar(perturb_std):
            return perturb_std
        return partial(interpolate_linear_1d, x=self.position, y=perturb_std) 
    
    
    def get_delta(self, position):
        if np.isscalar(self._delta):
            return self._delta
        return self._delta(position)
        
    
    def get_vmin_vmax(self, position):
        # It can return a scalar or an array or both
        # e.g.
        # >>> p.get_vmin_vmax(np.array([9.2, 8.7]))
        # (array([1.91111111, 1.85555556]), 3)
        vmin = self._vmin if np.isscalar(self._vmin) else self._vmin(position)
        vmax = self._vmax if np.isscalar(self._vmax) else self._vmax(position)
        return vmin, vmax
    
    
    def get_perturb_std(self, position):
        if np.isscalar(self._perturb_std):
            return self._perturb_std
        return self._perturb_std(position)    
    
    
    def generate_random_values(self, positions, is_init=False):
        vmin, vmax = self.get_vmin_vmax(positions)
        values = random.uniform(vmin, vmax)
        if is_init and self.init_sorted:
            return np.sort(values)
        return values
    
    
    def perturb_value(self, position, value):
        vmin, vmax = self.get_vmin_vmax(position)
        std = self.get_perturb_std(position)
        while True:
            random_deviate = random.normalvariate(0, std)
            new_value = value + random_deviate
            if not (new_value<vmin or new_value>vmax): 
                return new_value
    
    
    def prior_ratio_position_perturbation(self, old_position, new_position):
        delta_old = self.get_delta(old_position)
        delta_new = self.get_delta(new_position)
        return math.log(delta_old / delta_new)
    
    
    def prior_ratio_value_perturbation(self):
        return 0
    
    
    def proposal_ratio_value_perturbation(self):
        return 0
    
        
        
    
    
    
    
        

    
    
#%%

# param = Parameterization1D(n_voronoi_cells=5, 
#                            voronoi_site_bounds=(0, 10), 
#                            voronoi_site_perturb_std=[[1, 10], [1, 10]])
# p = PositionDependendentUniformParam('vs', 
#                                      position=[1, 10], 
#                                      vmin=[1, 2], 
#                                      vmax=3, 
#                                      perturb_std=0.1)
# param.add_free_parameter(p)

# print('VS')
# param.perturbation_free_param('vs')
# print(param.model.current_state)
# print(param.model.proposed_state)
# print('-'*15)
# param.finalize_perturbation(True)
# print(param.model.current_state)
# print(param.model.proposed_state)
# print('-'*15)

# print('SITE')
# param.perturbation_voronoi_site()
# print(param.model.current_state)
# print(param.model.proposed_state)
# print('-'*15)
# param.finalize_perturbation(True)
# print(param.model.current_state)
# print(param.model.proposed_state)


# print('BIRTH')
# param.perturbation_birth()
# print(param.model.current_state)
# print(param.model.proposed_state)
# print('-'*15)
# param.finalize_perturbation(True)
# print(param.model.current_state)
# print(param.model.proposed_state)


# print('DEATH')
# param.perturbation_death()
# print(param.model.current_state)
# print(param.model.proposed_state)
# print('-'*15)
# param.finalize_perturbation(True)
# print(param.model.current_state)
# print(param.model.proposed_state)
