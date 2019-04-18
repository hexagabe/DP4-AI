#!/usr/bin/env python

# -*- coding: utf-8 -*-
"""
Created on Wed Nov 19 15:56:54 2014

@author: ke291

Contains all of the Gaussian specific code for input generation and calculation
execution. Called by PyDP4.py.
"""

import subprocess
import socket
import os
import time
import math

import Gaussian

SetupNMRCalcs = Gaussian.SetupNMRCalcs

SetupECalcs = Gaussian.SetupECalcs

ReadShieldings = Gaussian.ReadShieldings

ReadDFTEnergies = Gaussian.ReadDFTEnergies

IsGausCompleted = Gaussian.IsGausCompleted

def RunNMRCalcs(Isomers, settings):
    print('\nRunning Gaussian NMR calculations on Ziggy...')

    # Run Gaussian jobs on Ziggy cluster in folder named after date and time
    # Split in batches, if needed

    jobdir = os.getcwd()
    os.chdir('nmr')

    GausJobs = []

    for iso in Isomers:
        GausJobs.extend([x for x in iso.NMRInputFiles if (x[:-4] + '.out') not in iso.NMROutputFiles])

    MaxCon = settings.MaxConcurrentJobs

    if len(GausJobs) < MaxCon:
        if len(GausJobs) > 0:
            RunOnZiggy(0, settings.queue, GausJobs, settings)
    else:
        if len(GausJobs) > 0:
            print("The DFT calculations will be done in " + \
                  str(math.ceil(len(GausJobs) / MaxCon)) + " batches")
            i = 0
            while (i + 1) * MaxCon < len(GausJobs):
                print("Starting batch nr " + str(i + 1))
                RunOnZiggy(str(i + 1), settings.queue, GausJobs[(i * MaxCon):((i + 1) * MaxCon)], settings)
                i += 1
            print("Starting batch nr " + str(i + 1))
            RunOnZiggy(str(i + 1), settings.queue, GausJobs[(i * MaxCon):], settings)

    NCompleted = 0
    Completed = []

    for f in GausJobs:
        if IsGausCompleted(f[:-4] + '.out'):
            Completed.append(f[:-4] + '.out')
            NCompleted += 1

    print(str(NCompleted) + "Gaussian jobs of " + str(len(GausJobs)) + \
        " completed successfully.")

    for iso in Isomers:
        iso.NMROutputFiles.extend([x[:-4] + '.out' for x in iso.NMRInputFiles if (x[:-4] + '.out') in Completed])

    os.chdir(jobdir)

    return Isomers


def RunOnZiggy(findex, queue, GausFiles, settings):

    if findex == 0:
        folder = settings.StartTime + settings.Title
    else:
        folder = settings.StartTime + findex + settings.Title

    scrfolder = settings.StartTime + settings.Title

    #Check that folder does not exist, create job folder on ziggy
    outp = subprocess.check_output('ssh ziggy ls', shell=True)
    if folder in outp.decode():
        print("Folder exists on ziggy, choose another folder name.")
        return

    outp = subprocess.check_output('ssh ziggy mkdir ' + folder, shell=True)

    print("Results folder: " + folder)

    #Write the qsub scripts
    for f in GausFiles:
        WriteSubScript(f, queue, folder, settings)
    print(str(len(GausFiles)) + ' slurm scripts generated')

    #Upload .com files and .qsub files to directory
    print("Uploading files to ziggy...")
    for f in GausFiles:
        outp = subprocess.check_output('scp ' + f +' ziggy:~/' + folder,
                                           shell=True)
        outp = subprocess.check_output('scp ' + f[:-4] +'slurm ziggy:~/' +
                                       folder, shell=True)

    print(str(len(GausFiles)) + ' .com and slurm files uploaded to ziggy')

    #Launch the calculations
    for f in GausFiles:
        job = '~/' + folder + '/' + f[:-4]
        outp = subprocess.check_output('ssh ziggy sbatch ' + job + 'slurm', shell=True)

    print(str(len(GausFiles)) + ' jobs submitted to the queue on ziggy')

    outp = subprocess.check_output('ssh ziggy qstat', shell=True)
    if settings.user in outp.decode():
        print("Jobs are running on ziggy")

    Jobs2Complete = list(GausFiles)
    n2complete = len(Jobs2Complete)

    #Check and report on the progress of calculations
    while len(Jobs2Complete) > 0:
        JustCompleted = [job for job in Jobs2Complete if
            IsZiggyGComplete(job[:-3] + 'out', folder, settings)]
        Jobs2Complete[:] = [job for job in Jobs2Complete if
             not IsZiggyGComplete(job[:-3] + 'out', folder, settings)]
        if n2complete != len(Jobs2Complete):
            n2complete = len(Jobs2Complete)
            print(str(n2complete) + " remaining.")

        time.sleep(60)

    #When done, copy the results back
    print("\nCopying the output files back to localhost...")
    print('ssh ziggy scp /home/' + settings.user + '/' + folder + '/*.out ' +\
        socket.getfqdn() + ':' + os.getcwd())
    outp = subprocess.check_output('ssh ziggy scp /home/' + settings.user +
                                   '/' + folder + '/*.out ' + socket.getfqdn()
                                   + ':' + os.getcwd(), shell=True)


def WriteSubScript(GausJob, queue, ZiggyJobFolder, settings):

    if not (os.path.exists(GausJob)):
        print("The input file " + GausJob + " does not exist. Exiting...")
        return

    #Create the submission script
    QSub = open(GausJob[:-4] + "slurm", 'w')

    #Choose the queue
    QSub.write('#!/bin/bash\n\n')
    QSub.write('#SBATCH -p SWAN\n')
    if settings.nProc >1:
        QSub.write('#SBATCH --nodes=1\n#SBATCH --cpus-per-task=' + str(settings.nProc) + '\n')
    else:
        QSub.write('#SBATCH --nodes=1\n#SBATCH --cpus-per-task=1\n')
    QSub.write('#SBATCH --time=' + format(settings.TimeLimit,"02") +':00:00\n\n')

    #define input files and output files
    QSub.write('file=' + GausJob[:-4] + '\n\n')
    QSub.write('inpfile=${file}.com\noutfile=${file}.out\n')

    #define cwd and scratch folder and ask the machine
    #to make it before running the job
    QSub.write('HERE=/home/' + settings.user +'/' + ZiggyJobFolder + '\n')
    QSub.write('SCRATCH=/scratch/' + settings.user + '/' +
               GausJob[:-4] + '\n')
    QSub.write('mkdir ${SCRATCH}\n')

    #Setup GAUSSIAN environment variables
    QSub.write('set OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK\n')
    
    QSub.write('export GAUSS_EXEDIR=/usr/local/shared/gaussian/em64t/09-D01/g09\n')
    QSub.write('export g09root=/usr/local/shared/gaussian/em64t/09-D01\n')
    QSub.write('export PATH=/usr/local/shared/gaussian/em64t/09-D01/g09:$PATH\n')
    QSub.write('export GAUSS_SCRDIR=$SCRATCH\n')
    QSub.write('exe=$GAUSS_EXEDIR/g09\n')
    #copy the input file to scratch
    QSub.write('cp ${HERE}/${inpfile}  $SCRATCH\ncd $SCRATCH\n')

    #write useful info to the job output file (not the gaussian)
    QSub.write('echo "Starting job $SLURM_JOBID"\necho\n')
    QSub.write('echo "SLURM assigned me this node:"\nsrun hostname\necho\n')

    QSub.write('ln -s $HERE/$outfile $SCRATCH/$outfile\n')
    QSub.write('srun $exe > $outfile < $inpfile\n')

    #Cleanup
    QSub.write('rm -rf ${SCRATCH}/\n')
    
    QSub.close()


def IsZiggyGComplete(f, folder, settings):

    path = '/home/' + settings.user + '/' + folder + '/'
    try:
        outp1 = subprocess.check_output('ssh ziggy ls ' + path, shell=True)
    except subprocess.CalledProcessError as e:
        print("ssh ziggy ls failed: " + str(e.output))
        return False
    if f in outp1.decode():
        try:
            outp2 = subprocess.check_output('ssh ziggy cat ' + path + f,
                                            shell=True)
        except subprocess.CalledProcessError as e:
            print("ssh ziggy cat failed: " + str(e.output).decode())
            return False
        if "Normal termination" in outp2[-90:].decode():
            return True
    return False
