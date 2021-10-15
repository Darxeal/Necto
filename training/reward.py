import numpy as np
from rlgym.utils import RewardFunction
from rlgym.utils.common_values import CEILING_Z, BALL_MAX_SPEED, CAR_MAX_SPEED, BLUE_TEAM
from rlgym.utils.gamestates import GameState, PlayerData


class NectoRewardFunction(RewardFunction):
    def __init__(
            self,
            team_spirit=0.3,
            goal_w=10,
            shot_w=5,
            save_w=5,
            demo_w=5,
            boost_w=0.5,
            touch_height_w=1,
            touch_accel_w=1,
            car_accel_w=0.05,
            cb_accel_w=0.05
    ):
        self.team_spirit = team_spirit
        self.last_state = None
        self.current_state = None
        self.rewards = None
        self.blue_rewards = None
        self.orange_rewards = None
        self.n = 0
        self.goal_w = goal_w
        self.shot_w = shot_w
        self.save_w = save_w
        self.demo_w = demo_w
        self.boost_w = boost_w
        self.touch_height_w = touch_height_w
        self.touch_accel_w = touch_accel_w
        self.car_accel_w = car_accel_w
        self.cb_accel_w = cb_accel_w

    def reset(self, initial_state: GameState):
        self.last_state = None
        self.current_state = initial_state
        self.rewards = np.zeros(len(initial_state.players))

    def _maybe_update_rewards(self, state: GameState):
        if state == self.current_state:
            return
        self.n = 0
        self.last_state = self.current_state
        self.current_state = state
        rewards = np.zeros(len(state.players))
        blue_mask = np.zeros_like(rewards, dtype=bool)
        orange_mask = np.zeros_like(rewards, dtype=bool)
        i = 0

        d_blue = state.blue_score - self.last_state.blue_score
        d_orange = state.orange_score - self.last_state.orange_score

        for old_p, new_p in zip(self.last_state.players, self.current_state.players):
            assert old_p.car_id == new_p.car_id
            # d_goal = new_p.match_goals - old_p.match_goals
            rew = (  # self.goal_w * d_goal +
                   self.shot_w * (new_p.match_shots - old_p.match_shots) +
                   self.save_w * (new_p.match_saves - old_p.match_saves) +
                   self.demo_w * (new_p.match_demolishes - old_p.match_demolishes) +
                   self.boost_w * max(new_p.boost_amount - old_p.boost_amount, 0))
            # Some napkin math: going around edge of field picking up 100 boost every second and gamma 0.995, skip 8
            # Discounted future reward in limit would be (0.5 / (1 * 15)) / (1 - 0.995) = 6.67 as a generous estimate
            # Pros are generally around maybe 400 bcpm, which would be 0.44 limit
            if new_p.ball_touched:
                # target = np.array(ORANGE_GOAL_BACK if new_p.team_num == BLUE_TEAM else BLUE_GOAL_BACK)
                curr_vel = self.current_state.ball.linear_velocity
                last_vel = self.last_state.ball.linear_velocity
                # On ground it gets about 0.05 just for touching, as well as some extra for the speed it produces
                # Close to 20 in the limit with ball on top, but opponents should learn to challenge way before that
                rew += (self.touch_height_w * state.ball.position[2] / CEILING_Z +
                        self.touch_accel_w * np.linalg.norm(curr_vel - last_vel) / BALL_MAX_SPEED)

            diff_abs_vel = (np.linalg.norm(new_p.car_data.linear_velocity)
                            - np.linalg.norm(old_p.car_data.linear_velocity))
            diff_vel = (new_p.car_data.linear_velocity
                        - old_p.car_data.linear_velocity)
            ball_dir = self.current_state.ball.position - new_p.car_data.position
            ball_dir = ball_dir / np.linalg.norm(ball_dir)
            accel_ball = np.dot(diff_vel, ball_dir)

            rew += (self.car_accel_w * diff_abs_vel / CAR_MAX_SPEED +
                    self.cb_accel_w * accel_ball / CAR_MAX_SPEED)

            rewards[i] = rew
            if new_p.team_num == BLUE_TEAM:
                blue_mask[i] = True
                # d_blue -= d_goal
            else:
                orange_mask[i] = True
                # d_orange -= d_goal
            i += 1

        # Handle goals with no scorer for critic consistency,
        # random state could send ball straight into goal
        if d_blue > 0:
            rewards[blue_mask] = d_blue * self.goal_w / blue_mask.sum()
        if d_orange > 0:
            rewards[orange_mask] = d_orange * self.goal_w / orange_mask.sum()

        blue_rewards = rewards[blue_mask]
        orange_rewards = rewards[orange_mask]
        blue_mean = np.nan_to_num(blue_rewards.mean())
        orange_mean = np.nan_to_num(orange_rewards.mean())
        self.rewards = np.zeros_like(rewards)
        self.rewards[blue_mask] = (1 - self.team_spirit) * blue_rewards + self.team_spirit * blue_mean - orange_mean
        self.rewards[orange_mask] = (1 - self.team_spirit) * orange_rewards + self.team_spirit * orange_mean - blue_mean

    def get_reward(self, player: PlayerData, state: GameState, previous_action: np.ndarray) -> float:
        self._maybe_update_rewards(state)
        rew = self.rewards[self.n]
        self.n += 1
        return rew / 1.6  # Approximate std at init is 1.6, helps the critic a little
