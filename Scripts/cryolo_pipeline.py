#!/usr/bin/env python

""" Cryolo Pipeline Script

Contains functions that handle the pipelining and processing of particle data
from the output of file_crawler.py, to a form usable by the Cryolo software
for both training and picking.

Can also be used as a standalone executable script.
Example usage: $cryolo_pipeline.py --job-folders Select2D_job030 Select3D_job033 --box-sizes 150 150
Optional parameters: config_fname, train_image_folder, train_annot_folder, saved_weights_name, pretrained_weights
"""

import os
import subprocess
import shutil
import warnings


def create_config_file(box_size, config_fname,
                       train_image_folder, train_annot_folder,
                       saved_weights_name, pretrained_weights=''):

    command = "cryolo_gui config %s %d --train_image_folder %s --train_annot_folder %s --saved_weights_name %s" %\
        (config_fname, box_size, train_image_folder,
         train_annot_folder, saved_weights_name)
    # Unlike the other options, pretrained weights will only be necessary in some use cases
    if pretrained_weights:
        command += " --pretrained_weights %s" % pretrained_weights

    subprocess.run(command, shell=True, stdout=subprocess.DEVNULL)

def train_model(config_fname):

    command = "cryolo_train -c %s -w 5 -g 0" % config_fname
    subprocess.run(command, shell=True)


def convert_to_cryolo_training(particle_data_file, box_size, output_image_folder,
                               output_annot_folder):
    """
    Converts the output of file_crawler.py's particle files 'data.txt' into
    the box format used by Cryolo for training data. Also arranges the micrograph
    files in separate train_image folder.
    """
    if not os.path.exists(output_image_folder):
        os.mkdir(output_image_folder)
    if not os.path.exists(output_annot_folder):
        os.mkdir(output_annot_folder)
    with open(particle_data_file, 'r') as data_f:
        all_data = data_f.read()
        all_data = all_data.split('$')[:-1]

        # the first element in the list would be particle metadata
        for mic_data in all_data[1:]:
            # list and filter func. used to get rid of empty strings just in case
            mic_name = list(filter(None, mic_data.split('\n')))[0].split()[-1]
            mic_path = os.path.normpath(os.path.join(particle_data_file, '../../../Micrographs/%s' % mic_name))
            if os.path.exists(mic_path):
                shutil.copy(mic_path, os.path.join(
                    output_image_folder, mic_name), follow_symlinks=False)
                box_file_path = os.path.join(
                    output_annot_folder, '%s.box' % os.path.splitext(mic_name)[0])
                with open(box_file_path, 'w') as box_f:
                    # the first element in the list would be the micrograph name
                    particle_data = list(filter(None, mic_data.split('\n')))[1:]
                    for particle in particle_data:
                        x, y = particle.split()
                        x = round(float(x))
                        y = round(float(y))
                        box_f.write('{:<4d}\t{:<4d}\t{:3d}\t{:3d}\n'.format(x, y, box_size, box_size))
            else:
                warnings.warn('Micrographs folder is missing %s: particle data \
                    related to it will not be used for training data.' % mic_name)


def cryolo_train_wrapper(job_folders=[], box_sizes=[], cryolo_output_folder='cryolo_training',
                    config_fname='config_cryolo.json', train_image_folder='train_image', train_annot_folder='train_annot',
                    saved_weights_name='cryolo_model.h5', pretrained_weights=''):
    """
    Automatically sets up the necessary box files, images and config files for
    training a Cryolo model from the job_folder output(s) of file_crawler.py,
    such as Refine3D_job035. It then trains a Cryolo model based on user-given settings.

    job_folders can be a simple particle job folder or a list of job folders which can be
    combined to train a Cryolo model. box_sizes contain the corresponding box sizes used
    to train the model.

    This method is implemented as a wrapper around the create_config_file and convert_to_cryolo_training functions,
    with additional code for handling box size calculations and parsing of data starting from the level of
    the job folder.
    """
    assert(len(job_folders) == len(box_sizes))
    os.mkdir(cryolo_output_folder)
    for i in range(len(job_folders)):
        job_folder = job_folders[i]
        box_size = box_sizes[i]
        convert_to_cryolo_training(particle_data_file=os.path.join(job_folder, 'data.txt'),
                                   box_size=box_size,
                                   output_image_folder=os.path.join(
                                       cryolo_output_folder, train_image_folder),
                                   output_annot_folder=os.path.join(cryolo_output_folder, train_annot_folder))

    # As per official Cryolo documentation, use the average box size for training when using
    # multiple datasets. An alternative is to try with the max box size.
    avg_box_size = int(sum(box_sizes) / len(box_sizes))
    # max_box_size = int(max(box_sizes_list))
    create_config_file(avg_box_size, config_fname=os.path.join(cryolo_output_folder, config_fname),
                       train_image_folder=train_image_folder,
                       train_annot_folder=train_annot_folder,
                       saved_weights_name=saved_weights_name,
                       pretrained_weights=pretrained_weights)

    # Currently using a Slurm script to run the training process for resource management
    # Don't do it directly from python
    # train_model(os.path.join(cryolo_output_folder, config_fname))
    # Consider automatically creating Slurm scripts and running them instead
    script_path = os.path.join(cryolo_output_folder, 'cryolo.slurm')
    with open(script_path, 'w') as slurm_f:
        slurm_f.write("#!/usr/bin/env bash\n")
        slurm_f.write("\n")
        slurm_f.write("#SBATCH --job-name ctrain\n")
        slurm_f.write("#SBATCH --partition jiang-gpu\n")
        slurm_f.write("#SBATCH --ntasks 1\n")
        slurm_f.write("#SBATCH --cpus-per-task 12\n")
        slurm_f.write("#SBATCH --gres gpu:2\n")
        slurm_f.write("#SBATCH --nodelist prp\n")
        slurm_f.write("#SBATCH --output %x.%j.stdout\n")
        slurm_f.write("#SBATCH --error %x.%j.stderr\n")
        slurm_f.write("\n")
        slurm_f.write("cryolo_train -c {} -w 5".format(config_fname))
        subprocess.run("sbatch {}".format(script_path), shell=True)


def cryolo_pick_wrapper(config_fname='config_cryolo.json', mics_dir='full_data', weights='cryolo_model.h5', output='boxfiles'):
    # Wrapper function that creates a Slurm script based on the given picking parameters and begins picking particles.

    with open('cryolo.slurm', 'w') as slurm_f:
        slurm_f.write("#!/usr/bin/env bash\n")
        slurm_f.write("\n")
        slurm_f.write("#SBATCH --job-name cpick\n")
        slurm_f.write("#SBATCH --partition jiang-gpu\n")
        slurm_f.write("#SBATCH --ntasks 1\n")
        slurm_f.write("#SBATCH --cpus-per-task 12\n")
        slurm_f.write("#SBATCH --gres gpu:1\n")
        slurm_f.write("#SBATCH --nodelist prp\n")
        slurm_f.write("#SBATCH --output %x.%j.stdout\n")
        slurm_f.write("#SBATCH --error %x.%j.stderr\n")
        slurm_f.write("\n")
        slurm_f.write("cryolo_predict -c {} -w {} -i {} -o {} -t 0.3".format(config_fname, weights, mics_dir, output))
        subprocess.run("sbatch cryolo.slurm", shell=True)
    

def main():
    job_folders = ['../Database/relion30_tutorial/Particles/Refine3D_job035',
                '../Database/P166/Particles/Homo_J14',
                '../Database/P171/Particles/Homo_J20',
                '../Database/P179/Particles/Homo_J23',
                '../Database/P180/Particles/Homo_J41',
                '../Database/P181/Particles/Homo_J22',
                '../Database/P190/Particles/Homo_J38',
                '../Database/P192/Particles/Homo_J29']
    box_sizes = [300, 300, 300, 300, 300, 300, 300, 300]
    cryolo_wrapper(job_folders = job_folders,
            box_sizes = box_sizes)



if __name__ == '__main__':
    main()