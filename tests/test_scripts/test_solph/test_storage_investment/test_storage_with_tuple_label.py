# -*- coding: utf-8 -*-

"""
General description:
---------------------

The example models the following energy system:

                input/output  bgas     bel
                     |          |        |       |
                     |          |        |       |
 wind(FixedSource)   |------------------>|       |
                     |          |        |       |
 pv(FixedSource)     |------------------>|       |
                     |          |        |       |
 rgas(Commodity)     |--------->|        |       |
                     |          |        |       |
 demand(Sink)        |<------------------|       |
                     |          |        |       |
                     |          |        |       |
 pp_gas(Transformer) |<---------|        |       |
                     |------------------>|       |
                     |          |        |       |
 storage(Storage)    |<------------------|       |
                     |------------------>|       |



This file is part of project oemof (github.com/oemof/oemof). It's copyrighted
by the contributors recorded in the version control history of the file,
available from its original location oemof/tests/test_scripts/test_solph/
test_storage_investment/test_storage_investment.py

SPDX-License-Identifier: GPL-3.0-or-later
"""

from nose.tools import eq_
from collections import namedtuple

import oemof.solph as solph
from oemof.network import Node
from oemof.outputlib import processing, views

import logging
import os
import pandas as pd


class Label(namedtuple('solph_label', ['tag1', 'tag2', 'tag3'])):
    __slots__ = ()

    def __str__(self):
        return '_'.join(map(str, self._asdict().values()))


def test_label():
    my_label = Label('arg', 5, None)
    eq_(str(my_label), 'arg_5_None')
    eq_(repr(my_label), "Label(tag1='arg', tag2=5, tag3=None)")


def test_optimise_storage_size(filename="storage_investment.csv",
                               solver='cbc'):

    logging.info('Initialize the energy system')
    date_time_index = pd.date_range('1/1/2012', periods=400, freq='H')

    energysystem = solph.EnergySystem(timeindex=date_time_index)
    Node.registry = energysystem

    full_filename = os.path.join(os.path.dirname(__file__), filename)
    data = pd.read_csv(full_filename, sep=",")

    # Buses
    bgas = solph.Bus(label=Label('bus', 'natural_gas', None))
    bel = solph.Bus(label=Label('bus', 'electricity', ''))

    # Sinks
    solph.Sink(label=Label('sink', 'electricity', 'excess'),
               inputs={bel: solph.Flow()})

    solph.Sink(label=Label('sink', 'electricity', 'demand'),
               inputs={bel: solph.Flow(
                   actual_value=data['demand_el'],
                   fixed=True, nominal_value=1)})

    # Sources
    solph.Source(label=Label('source', 'natural_gas', 'commodity'),
                 outputs={bgas: solph.Flow(
                     nominal_value=194397000 * 400 / 8760, summed_max=1)})

    solph.Source(label=Label('renewable', 'electricity', 'wind'),
                 outputs={bel: solph.Flow(
                     actual_value=data['wind'],
                     nominal_value=1000000, fixed=True)})

    solph.Source(label=Label('renewable', 'electricity', 'pv'),
                 outputs={bel: solph.Flow(
                     actual_value=data['pv'], nominal_value=582000,
                     fixed=True)})

    # Transformer
    solph.Transformer(
        label=Label('pp', 'electricity', 'natural_gas'),
        inputs={bgas: solph.Flow()},
        outputs={bel: solph.Flow(nominal_value=10e10, variable_costs=50)},
        conversion_factors={bel: 0.58})

    # Investment storage
    solph.components.GenericStorage(
        label=Label('storage', 'electricity', 'battery'),
        nominal_capacity=2046852,
        inputs={bel: solph.Flow(variable_costs=10e10)},
        outputs={bel: solph.Flow(variable_costs=10e10)},
        capacity_loss=0.00, initial_capacity=0,
        invest_relation_input_capacity=1/6,
        invest_relation_output_capacity=1/6,
        inflow_conversion_factor=1, outflow_conversion_factor=0.8,
    )

    # Solve model
    om = solph.Model(energysystem)
    om.solve(solver=solver)
    energysystem.results['main'] = processing.results(om)
    energysystem.results['meta'] = processing.meta_results(om)

    # Check dump and restore
    energysystem.dump()
    es = solph.EnergySystem()
    es.restore()

    # Results
    results = es.results['main']
    meta = es.results['meta']

    electricity_bus = views.node(results, 'bus_electricity_')
    my_results = electricity_bus['sequences'].sum(axis=0).to_dict()
    storage = es.groups['storage_electricity_battery']
    storage_node = views.node(results, storage)
    my_results['max_load'] = storage_node['sequences'].max()[
        ((storage, None), 'capacity')]
    commodity_bus = views.node(results, 'bus_natural_gas_None')

    gas_usage = commodity_bus['sequences'][
        (('source_natural_gas_commodity', 'bus_natural_gas_None'), 'flow')]

    my_results['gas_usage'] = gas_usage.sum()

    stor_invest_dict = {
        'gas_usage': 8876575,
        'max_load': 2046851,
        (('bus_electricity_', 'sink_electricity_demand'), 'flow'): 105867395,
        (('bus_electricity_', 'sink_electricity_excess'), 'flow'): 211771291,
        (('bus_electricity_', 'storage_electricity_battery'), 'flow'): 2350931,
        (('pp_electricity_natural_gas', 'bus_electricity_'), 'flow'): 5148414,
        (('renewable_electricity_pv', 'bus_electricity_'), 'flow'): 7488607,
        (('renewable_electricity_wind', 'bus_electricity_'),
            'flow'): 305471851,
        (('storage_electricity_battery', 'bus_electricity_',),
            'flow'): 1880745}

    for key in stor_invest_dict.keys():
        eq_(int(round(my_results[key])), int(round(stor_invest_dict[key])))

    # Solver results
    eq_(str(meta['solver']['Termination condition']), 'optimal')
    eq_(meta['solver']['Error rc'], 0)
    eq_(str(meta['solver']['Status']), 'ok')

    # Problem results
    eq_(meta['problem']['Lower bound'], 4.231675775e+17)
    eq_(meta['problem']['Upper bound'], 4.231675775e+17)
    eq_(meta['problem']['Number of variables'], 2800)
    eq_(meta['problem']['Number of constraints'], 1602)
    eq_(meta['problem']['Number of nonzeros'], 5199)
    eq_(meta['problem']['Number of objectives'], 1)
    eq_(str(meta['problem']['Sense']), 'minimize')

    # Objective function
    eq_(round(meta['objective']), 423167578097420672)
