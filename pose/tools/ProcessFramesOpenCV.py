from __future__ import print_function, unicode_literals

# Note: I am having installation issues with OpenCV's VideoCapture. But this
# code should be working.
# If you have encountered some bug, please post it in issues and I will try to look into it.
# Else you can look into the processing by MoviePy present in ProcessFramesMoviePy.py file.

import tensorflow as tf
import numpy as np
import scipy.misc
import os
import argparse
import operator
import csv
import cv2

from data.nets.ColorHandPose3DNetwork import ColorHandPose3DNetwork
from utils.general import detect_keypoints, trafo_coords, plot_hand, plot_hand_2d, plot_hand_3d
from pose.DeterminePositions import *
from pose.utils.FingerPoseEstimate import FingerPoseEstimate

def parse_args():
	parser = argparse.ArgumentParser(description = 'Process frames in a video of a particular pose')
	parser.add_argument('video_path', help = 'Path of video', type = str)
	# This part needs improvement. Currently, pose_no is position_id present in FingerDataFormation.py 
	parser.add_argument('pose_no', help = 'Pose to classify at', type = int)
	parser.add_argument('--output-path', dest = 'output_path', type = str, default = None,
						help = 'Path of folder where to store the text output')
	parser.add_argument('--thresh', dest = 'threshold', help = 'Threshold of confidence level(0-1)', default = 0.45,
	                    type = float)
	parser.add_argument('--save-video', dest = 'save_video', type = int, default = 0,
						help = 'Should output video be saved (1 = Yes, 0 = No)')
	args = parser.parse_args()
	return args

def prepare_paths(video_path, output_txt_path, save_video):
	video_path = os.path.abspath(video_path)

	if output_txt_path is None:
		output_txt_path = os.path.split(video_path)[0]
	else:
		output_txt_path = os.path.abspath(output_txt_path)
		if not os.path.exists(output_txt_path):
			os.mkdir(output_txt_path)

	file_name = os.path.basename(video_path).split('.')[0]
	output_video_path = None if save_video == 0 else os.path.join(output_txt_path, '{}_save.mp4'.format(file_name))
	output_txt_path = os.path.join(output_txt_path, '{}.csv'.format(file_name))
	if not os.path.exists(output_txt_path):
		open(output_txt_path, 'w').close()
	return video_path, output_txt_path, output_video_path

def prepare_network():
	# network input
	image_tf = tf.placeholder(tf.float32, shape = (1, 240, 320, 3))
	hand_side_tf = tf.constant([[1.0, 1.0]])  # Both left and right hands included
	evaluation = tf.placeholder_with_default(True, shape = ())

	# build network
	net = ColorHandPose3DNetwork()
	hand_scoremap_tf, image_crop_tf, scale_tf, center_tf,\
		keypoints_scoremap_tf, keypoint_coord3d_tf = net.inference(image_tf, hand_side_tf, evaluation)

	# Start TF
	gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=0.8)
	sess = tf.Session(config=tf.ConfigProto(gpu_options=gpu_options))

	# initialize network
	net.init(sess)

	return sess, image_tf, keypoint_coord3d_tf, scale_tf, center_tf, keypoints_scoremap_tf

def process_video_frame(video_frame, image_tf, threshold, save_video,
					    known_finger_poses, output_txt_path, reqd_pose_name, network_elements):
	video_frame = video_frame[:, :, :3]
	video_frame = scipy.misc.imresize(video_frame, (240, 320))
	image_v = np.expand_dims((video_frame.astype('float') / 255.0) - 0.5, 0)

	if save_video == 1:
		keypoint_coord3d_tf, scale_tf, center_tf, keypoints_scoremap_tf = network_elements
		keypoint_coord3d_v, scale_v, center_v, keypoints_scoremap_v = sess.run([keypoint_coord3d_tf,
			scale_tf, center_tf, keypoints_scoremap_tf], feed_dict = {image_tf: image_v})

		keypoints_scoremap_v = np.squeeze(keypoints_scoremap_v)
		keypoint_coord3d_v = np.squeeze(keypoint_coord3d_v)

		# post processing
		coord_hw_crop = detect_keypoints(np.squeeze(keypoints_scoremap_v))
		coord_hw = trafo_coords(coord_hw_crop, center_v, scale_v, 256)

		plot_hand_2d(coord_hw, video_frame)
	else:
		keypoint_coord3d_tf = network_elements
		keypoint_coord3d_v = sess.run(keypoint_coord3d_tf, feed_dict = {image_tf: image_v})

	score_label = process_keypoints(keypoint_coord3d_v, threshold, known_finger_poses,
								 output_txt_path, reqd_pose_name)
	if save_video == 1 and score_label is not None:
		font = cv2.FONT_HERSHEY_SIMPLEX
		cv2.putText(video_frame, score_label, (10, 200), font, 1.0, (255, 0, 0), 2, cv2.LINE_AA)
		
	return video_frame

def process_keypoints(keypoint_coord3d_v, threshold, known_finger_poses, output_txt_path, reqd_pose_name):
	fingerPoseEstimate = FingerPoseEstimate(keypoint_coord3d_v)
	fingerPoseEstimate.calculate_positions_of_fingers(print_finger_info = False)
	obtained_positions = determine_position(fingerPoseEstimate.finger_curled, 
										fingerPoseEstimate.finger_position, known_finger_poses,
										threshold)

	score_label = None
	if len(obtained_positions) > 0:
		max_pose_label = max(obtained_positions.items(), key=operator.itemgetter(1))[0]
		if obtained_positions[max_pose_label] >= threshold and max_pose_label == reqd_pose_name:
			score_label = max_pose_label
			with open(output_txt_path, 'a') as fid:
				list_entry = [entry for sublist in keypoint_coord3d_v for entry in sublist]
				csv_writer = csv.writer(fid)
				csv_writer.writerow(list_entry)
	
	return score_label

if __name__ == '__main__':
	args = parse_args()
	video_path, output_txt_path, output_video_path = prepare_paths(args.video_path, args.output_path,
																   args.save_video)
	known_finger_poses = create_known_finger_poses()
	reqd_pose_name = get_position_name_with_pose_id(args.pose_no, known_finger_poses)
								
	if args.save_video:
		sess, image_tf, keypoint_coord3d_tf, scale_tf, center_tf, keypoints_scoremap_tf = prepare_network()
		network_elements = [keypoint_coord3d_tf, scale_tf, center_tf, keypoints_scoremap_tf]
	else:
		sess, image_tf, keypoint_coord3d_tf, _, _, _ = prepare_network()
		network_elements = [keypoint_coord3d_tf]
		
	video_clip = cv2.VideoCapture(video_path)
	if args.save_video:
		fourcc = cv2.VideoWriter_fourcc(*'XVID')
		video_out = cv2.VideoWriter(output_video_path, fourcc, 20.0, (640,480))

	while video_clip.isOpened():
		# Capture frame-by-frame
		ret, video_frame = video_clip.read()
		if not ret:
			break

		video_frame = process_video_frame(video_frame, image_tf, args.threshold * 10, args.save_video, 
										  known_finger_poses, output_txt_path, reqd_pose_name, network_elements)
		if args.save_video:
			video_out.write(video_frame)

	video_clip.release()
	if args.save_video:
		video_out.release()
