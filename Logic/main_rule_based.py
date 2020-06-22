from datetime import datetime
import os
import pandas as pd
import rule_experience
import rule_utils
from shutil import copyfile
from skopt import Optimizer
import utils

# Make sure the data is deterministic
import numpy as np
import random
np.random.seed(0)
random.seed(0)

NUM_GAMES = 20
config = {
  'max_pool_size': 30, # 1 Means pure self play
  'num_games_previous_pools': NUM_GAMES*0,
  'num_games_evaluation': NUM_GAMES*0,
  'num_games_fixed_opponents_pool': NUM_GAMES,
  'max_experience_buffer': 10000,
  'min_new_iteration_win_rate': 0.6,
  'record_videos_new_iteration': True,
  'record_videos_each_main_loop': True,
  'save_experience_data_to_disk': True,
  'use_multiprocessing': False,
  'play_fixed_pool_only': True,
  'play_fixed_pool_fit_prev_data': True,
  'fixed_opponents_num_repeat_first_configs': NUM_GAMES,
  
  'num_agents_per_game': 4,
  'pool_name': 'Rule based with evolution I',

  # You need to delete the earlier configs or delete an entire agent pool after
  # making changes to the search ranges
  'initial_config_ranges':{
    'halite_config_setting_divisor': ((1000.0, 20000.0), "float", 0),
    'max_ship_to_base_ratio': ((4.0, 12.0), "float", 0),
    
    'min_spawns_after_conversions': ((0, 3), "int", 0),
    'max_conversions_per_step': ((1, 4), "int", 1),
    'ship_halite_cargo_conversion_bonus_constant': ((0.0, 20.0), "float", 0),
    'friendly_ship_halite_conversion_constant': ((0.0, 2.0), "float", 0),
    'friendly_bases_conversion_constant': ((5.0, 200.0), "float", 0),
    'nearby_halite_conversion_constant': ((0.0, 2.0), "float", 0),
    'conversion_score_threshold': ((0.0, 30.0), "float", -float("inf")),
    
    'halite_collect_constant': ((0.0, 50.0), "float", 0),
    'nearby_halite_move_constant': ((0.0, 30.0), "float", 0),
    'nearby_onto_halite_move_constant': ((0.0, 20.0), "float", 0),
    'nearby_ships_move_constant': ((0.0, 1.0), "float", 0),
    'nearby_base_move_constant': ((0.0, 20.0), "float", 0),
    'nearby_move_onto_base_constant': ((0.0, 50.0), "float", 0),
    'adjacent_opponent_ships_move_constant': ((0.0, 20.0), "float", 0),
    
    'max_spawns_per_step': ((1, 10), "int", 1),
    'nearby_ship_halite_spawn_constant': ((0.0, 2.0), "float", 0),
    'nearby_halite_spawn_constant': ((0.0, 20.0), "float", 0),
    'remaining_budget_spawn_constant': ((0.002, 0.1), "float", 0),
    'spawn_score_threshold': ((0.0, 40.0), "float", -float("inf")),
    }
  }
CONFIG_SETTINGS_EXTENSION = "config_settings_scores.csv"

def main_rule_utils(config):
  rule_utils.store_config_on_first_run(config)
  experience_buffer = utils.ExperienceBuffer(config['max_experience_buffer'])
  config_keys = list(config['initial_config_ranges'].keys())
  
  fixed_pool_mode = config['play_fixed_pool_only']
  if fixed_pool_mode:
    fixed_opp_repeats = config['fixed_opponents_num_repeat_first_configs']
    # Prepare the Bayesian optimizer
    opt_range = [config['initial_config_ranges'][k][0] for k in config_keys]
    opt = Optimizer(opt_range)
    
    if config['play_fixed_pool_fit_prev_data']:
      fixed_pool_experience_path = rule_utils.get_self_play_experience_path(
        config['pool_name'])
      if os.path.exists(fixed_pool_experience_path):
        print('\nBayesian fit to earlier experiments')
        this_folder = os.path.dirname(__file__)
        agents_folder = os.path.join(
          this_folder, '../Rule agents/' + config['pool_name'])
        config_settings_path = os.path.join(
          agents_folder, CONFIG_SETTINGS_EXTENSION)
        if os.path.exists(config_settings_path):
          config_results = pd.read_csv(config_settings_path)
          suggested = config_results.iloc[:, :-1].values.tolist()
          target_scores = (-config_results.iloc[:, -1].values).tolist()
          opt.tell(suggested, target_scores)
          # import pdb; pdb.set_trace()
          # print(opt.get_result().x, opt.get_result().fun) # WRONG!
        
    next_fixed_opponent_suggested = None
    iteration_config_rewards = None
    experience_features_rewards_path = None
  
  while True:
    # Section 1: play games against agents of N previous pools
    if config['num_games_previous_pools'] and not fixed_pool_mode:
      print('\nPlay vs other rule based agents from the last {} pools'.format(
        config['max_pool_size']))
      (self_play_experience, rules_config_path,
       avg_reward_sp, _) = rule_experience.play_games(
          pool_name=config['pool_name'],
          num_games=config['num_games_previous_pools'],
          max_pool_size=config['max_pool_size'],
          num_agents=config['num_agents_per_game'],
          exclude_current_from_opponents=False,
          record_videos_new_iteration=config['record_videos_new_iteration'],
          initial_config_ranges=config['initial_config_ranges'],
          use_multiprocessing=config['use_multiprocessing'],
          )
      experience_buffer.add(self_play_experience)
    
    # Section 2: play games against agents of the previous pool
    if config['num_games_evaluation'] and not fixed_pool_mode:
      print('\nPlay vs previous iteration')
      (evaluation_experience, rules_config_path,
       avg_reward_eval, _) = rule_experience.play_games(
          pool_name=config['pool_name'],
          num_games=config['num_games_evaluation'],
          max_pool_size=2,
          num_agents=config['num_agents_per_game'],
          exclude_current_from_opponents=True,
          use_multiprocessing=config['use_multiprocessing'],
          )
      # experience_buffer.add(evaluation_experience)
         
    if fixed_pool_mode:
      if iteration_config_rewards is not None:
        # Update the optimizer using the most recent fixed opponent pool
        # results
        target_scores = np.reshape(-iteration_config_rewards[
          'episode_reward'].values, [-1, fixed_opp_repeats]).mean(1).tolist()
        opt.tell(next_fixed_opponent_suggested, target_scores)
        
        # Append the tried settings to the settings-scores file
        config_rewards = rule_utils.append_config_scores(
          next_fixed_opponent_suggested, target_scores, config_keys,
          config['pool_name'], CONFIG_SETTINGS_EXTENSION)
        
        # Update the plot of the tried settings and obtained scores
        rule_utils.plot_reward_versus_features(
          experience_features_rewards_path, config_rewards,
          target_col="Average win rate", include_all_targets=True,
          plot_name_suffix="config setting average win rate", all_scatter=True)
      
      # Select the next hyperparameters to try
      next_fixed_opponent_suggested, next_fixed_opponent_configs = (
        rule_utils.get_next_config_settings(
          opt, config_keys, config['num_games_fixed_opponents_pool'],
          fixed_opp_repeats)
        )
         
    # Section 3: play games against a fixed opponents pool
    if config['num_games_fixed_opponents_pool']:
      print('\nPlay vs the fixed opponents pool')
      (fixed_opponents_experience, rules_config_path,
       avg_reward_fixed_opponents, opponent_rewards) = (
         rule_experience.play_games(
           pool_name=config['pool_name'],
           num_games=config['num_games_fixed_opponents_pool'],
           max_pool_size=1, # Any positive integer is fine
           num_agents=config['num_agents_per_game'],
           exclude_current_from_opponents=False,
           fixed_opponent_pool=True,
           initial_config_ranges=config['initial_config_ranges'],
           use_multiprocessing=config['use_multiprocessing'],
           num_repeat_first_configs=fixed_opp_repeats,
           first_config_overrides=next_fixed_opponent_configs,
           )
         )
      # experience_buffer.add(evaluation_experience)
         
    # Select the values that will be used to determine if a next iteration file
    # will be created
    serialized_raw_experience = fixed_opponents_experience if (
      fixed_pool_mode) else self_play_experience
         
    # Optionally append the experience of interest to disk
    iteration_config_rewards = (
      rule_utils.serialize_game_experience_for_learning(
        serialized_raw_experience, fixed_pool_mode, config_keys))
    if config['save_experience_data_to_disk']:
      experience_features_rewards_path = rule_utils.write_experience_data(
        config['pool_name'], iteration_config_rewards)
         
    # Section 4: Update the iteration, store videos and record learning
    # progress.
    if fixed_pool_mode:
      update_config = {'Time stamp': str(datetime.now())}
      for i in range(len(opponent_rewards)):
        update_config['Reward ' + opponent_rewards[i][2]] = np.round(
          opponent_rewards[i][1]/(1e-10+opponent_rewards[i][0]), 2)
      rule_utils.update_learning_progress(config['pool_name'], update_config)

      config_override_agents = (
        fixed_opponents_experience[-1].config_game_agents)
      rule_utils.record_videos(
        rules_config_path, config['num_agents_per_game'],
        extension_override=str(datetime.now())[:19],
        config_override_agents=config_override_agents)
    else:
      # Save a new iteration if it has significantly improved
      data_rules_path = rules_config_path
      if min(avg_reward_sp, avg_reward_eval) >= config[
          'min_new_iteration_win_rate']:
        original_rules_config_path = rules_config_path
        incremented_rules_path = utils.increment_iteration_id(
          rules_config_path, extension='.json')
        copyfile(rules_config_path, incremented_rules_path)
        rules_config_path = incremented_rules_path
        
        if config['record_videos_new_iteration']:
          rule_utils.record_videos(original_rules_config_path,
                                   config['num_agents_per_game'],
                                   )
      elif config['record_videos_each_main_loop']:
        rule_utils.record_videos(rules_config_path,
                                 config['num_agents_per_game'],
                                 str(datetime.now())[:19])
        
      # Record learning progress
      rule_utils.update_learning_progress(config['pool_name'], {
        'Time stamp': str(datetime.now()),
        'Average reward self play': avg_reward_sp,
        'Average evaluation reward': avg_reward_eval,
        'Experience buffer size': experience_buffer.size(),
        'Data rules path': data_rules_path,
        })
    
    # Section 5: Update the latest config range using the data in the
    # experience buffer
    if rules_config_path is not None:
      if not fixed_pool_mode:
        # Evolve the config ranges in a very simple gradient free way.
        rule_utils.evolve_config(
          rules_config_path, iteration_config_rewards,
          config['initial_config_ranges'])
      
      # Create plot(s) of the terminal reward as a function of all serialized
      # features
      if config['save_experience_data_to_disk']:
        rule_utils.plot_reward_versus_features(
          experience_features_rewards_path, iteration_config_rewards,
          plot_name_suffix=str(datetime.now())[:19])
    
main_rule_utils(config)