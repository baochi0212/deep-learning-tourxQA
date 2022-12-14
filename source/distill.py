from my_summary import summary
import logging
import numpy as np
import os
import sys
sys.path.append(os.environ['source'])
import torch
from torch.utils import data
import torch.nn as nn

from tqdm.auto import tqdm
from early_stopping import EarlyStopping

from transformers import AdamW, get_linear_schedule_with_warmup, AutoTokenizer, AutoConfig
from data_loader import load_and_cache_examples
from modules.IDSF import IDSFModule
from modules.QA import QAModule
from utils import *
from main import args
from data_loader import *
from model.IDSF_modules import *
logger = logging.getLogger(__name__)
import os
from copy import deepcopy
from teacher_config import teacher_args
from student_config import student_args
from modules.IDSF import IDSFModule
from modules.QA import QAModule

import matplotlib.pyplot as plt
import torch
import torch.nn as nn
from torch.utils.tensorboard import SummaryWriter
import os
from copy import deepcopy

import matplotlib.pyplot as plt
import torch
import torch.nn as nn
from torch.utils.tensorboard import SummaryWriter

from trainer import Trainer_IDSF


class BaseClass:
    """
    Basic implementation of a general Knowledge Distillation framework

    :param teacher_model (torch.nn.Module): Teacher model
    :param student_model (torch.nn.Module): Student model
    :param train_loader (torch.utils.data.DataLoader): Dataloader for training
    :param val_loader (torch.utils.data.DataLoader): Dataloader for validation/testing
    :param optimizer_teacher (torch.optim.*): Optimizer used for training teacher
    :param optimizer_student (torch.optim.*): Optimizer used for training student
    :param loss_fn (torch.nn.Module): Loss Function used for distillation
    :param temp (float): Temperature parameter for distillation
    :param distil_weight (float): Weight paramter for distillation loss
    :param device (str): Device used for training; 'cpu' for cpu and 'cuda' for gpu
    :param log (bool): True if logging required
    :param logdir (str): Directory for storing logs
    """

    def __init__(
        self,
        teacher_model,
        student_model,
        train_loader,
        val_loader,
        optimizer_teacher,
        optimizer_student,
        loss_fn=nn.KLDivLoss(),
        temp=20.0,
        distil_weight=0.5,
        device="cpu",
        log=False,
        logdir="./Experiments",
    ):

        self.train_loader = train_loader
        self.val_loader = val_loader
        self.optimizer_teacher = optimizer_teacher
        self.optimizer_student = optimizer_student
        self.temp = temp
        self.distil_weight = distil_weight
        self.log = log
        self.logdir = logdir

        if self.log:
            self.writer = SummaryWriter(logdir)

        if device == "cpu":
            self.device = torch.device("cpu")
        elif device == "cuda":
            if torch.cuda.is_available():
                self.device = torch.device("cuda")
            else:
                print(
                    "Either an invalid device or CUDA is not available. Defaulting to CPU."
                )
                self.device = torch.device("cpu")

        if teacher_model:
            self.teacher_model = teacher_model.to(self.device)
        else:
            print("Warning!!! Teacher is NONE.")

        self.student_model = student_model.to(self.device)
        self.loss_fn = loss_fn.to(self.device)
        self.ce_fn = nn.CrossEntropyLoss().to(self.device)

    def train_teacher(
        self,
        epochs=20,
        plot_losses=True,
        save_model=True,
        save_model_pth="./models/teacher.pt",
    ):
        """
        Function that will be training the teacher

        :param epochs (int): Number of epochs you want to train the teacher
        :param plot_losses (bool): True if you want to plot the losses
        :param save_model (bool): True if you want to save the teacher model
        :param save_model_pth (str): Path where you want to store the teacher model
        """
        self.teacher_model.train()
        loss_arr = []
        length_of_dataset = len(self.train_loader.dataset)
        best_acc = 0.0
        self.best_teacher_model_weights = deepcopy(self.teacher_model.state_dict())

        save_dir = os.path.dirname(save_model_pth)
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        print("Training Teacher... ")

        for ep in range(epochs):
            epoch_loss = 0.0
            correct = 0
            for (data, label) in self.train_loader:
                data = data.to(self.device)
                label = label.to(self.device)
                out = self.teacher_model(data)

                if isinstance(out, tuple):
                    out = out[0]

                pred = out.argmax(dim=1, keepdim=True)
                correct += pred.eq(label.view_as(pred)).sum().item()

                loss = self.ce_fn(out, label)

                self.optimizer_teacher.zero_grad()
                loss.backward()
                self.optimizer_teacher.step()

                epoch_loss += loss.item()

            epoch_acc = correct / length_of_dataset

            epoch_val_acc = self.evaluate(teacher=True)

            if epoch_val_acc > best_acc:
                best_acc = epoch_val_acc
                self.best_teacher_model_weights = deepcopy(
                    self.teacher_model.state_dict()
                )

            if self.log:
                self.writer.add_scalar("Training loss/Teacher", epoch_loss, epochs)
                self.writer.add_scalar("Training accuracy/Teacher", epoch_acc, epochs)
                self.writer.add_scalar(
                    "Validation accuracy/Teacher", epoch_val_acc, epochs
                )

            loss_arr.append(epoch_loss)
            print(
                "Epoch: {}, Loss: {}, Accuracy: {}".format(
                    ep + 1, epoch_loss, epoch_acc
                )
            )

            self.post_epoch_call(ep)

        self.teacher_model.load_state_dict(self.best_teacher_model_weights)
        if save_model:
            torch.save(self.teacher_model.state_dict(), save_model_pth)
        if plot_losses:
            plt.plot(loss_arr)

    def _train_student(
        self,
        epochs=10,
        plot_losses=True,
        save_model=True,
        save_model_pth="./models/student.pt",
    ):
        """
        Function to train student model - for internal use only.

        :param epochs (int): Number of epochs you want to train the teacher
        :param plot_losses (bool): True if you want to plot the losses
        :param save_model (bool): True if you want to save the student model
        :param save_model_pth (str): Path where you want to save the student model
        """
        self.teacher_model.eval()
        self.student_model.train()
        loss_arr = []
        length_of_dataset = len(self.train_loader.dataset)
        best_acc = 0.0
        self.best_student_model_weights = deepcopy(self.student_model.state_dict())

        save_dir = os.path.dirname(save_model_pth)
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        print("Training Student...")

        for ep in range(epochs):
            epoch_loss = 0.0
            correct = 0

            for (data, label) in self.train_loader:

                data = data.to(self.device)
                label = label.to(self.device)

                student_out = self.student_model(data)
                teacher_out = self.teacher_model(data)

                loss = self.calculate_kd_loss(student_out, teacher_out, label)

                if isinstance(student_out, tuple):
                    student_out = student_out[0]

                pred = student_out.argmax(dim=1, keepdim=True)
                correct += pred.eq(label.view_as(pred)).sum().item()

                self.optimizer_student.zero_grad()
                loss.backward()
                self.optimizer_student.step()

                epoch_loss += loss.item()

            epoch_acc = correct / length_of_dataset

            _, epoch_val_acc = self._evaluate_model(self.student_model, verbose=True)

            if epoch_val_acc > best_acc:
                best_acc = epoch_val_acc
                self.best_student_model_weights = deepcopy(
                    self.student_model.state_dict()
                )

            if self.log:
                self.writer.add_scalar("Training loss/Student", epoch_loss, epochs)
                self.writer.add_scalar("Training accuracy/Student", epoch_acc, epochs)
                self.writer.add_scalar(
                    "Validation accuracy/Student", epoch_val_acc, epochs
                )

            loss_arr.append(epoch_loss)
            print(
                "Epoch: {}, Loss: {}, Accuracy: {}".format(
                    ep + 1, epoch_loss, epoch_acc
                )
            )

        self.student_model.load_state_dict(self.best_student_model_weights)
        if save_model:
            torch.save(self.student_model.state_dict(), save_model_pth)
        if plot_losses:
            plt.plot(loss_arr)

    def train_student(
        self,
        epochs=10,
        plot_losses=True,
        save_model=True,
        save_model_pth="./models/student.pt",
    ):
        """
        Function that will be training the student

        :param epochs (int): Number of epochs you want to train the teacher
        :param plot_losses (bool): True if you want to plot the losses
        :param save_model (bool): True if you want to save the student model
        :param save_model_pth (str): Path where you want to save the student model
        """
        self._train_student(epochs, plot_losses, save_model, save_model_pth)

    def calculate_kd_loss(self, y_pred_student, y_pred_teacher, y_true):
        """
        Custom loss function to calculate the KD loss for various implementations

        :param y_pred_student (Tensor): Predicted outputs from the student network
        :param y_pred_teacher (Tensor): Predicted outputs from the teacher network
        :param y_true (Tensor): True labels
        """

        raise NotImplementedError

    def _evaluate_model(self, model, verbose=True):
        """
        Evaluate the given model's accuaracy over val set.
        For internal use only.

        :param model (nn.Module): Model to be used for evaluation
        :param verbose (bool): Display Accuracy
        """
        model.eval()
        length_of_dataset = len(self.val_loader.dataset)
        correct = 0
        outputs = []

        with torch.no_grad():
            for data, target in self.val_loader:
                data = data.to(self.device)
                target = target.to(self.device)
                output = model(data)

                if isinstance(output, tuple):
                    output = output[0]
                outputs.append(output)

                pred = output.argmax(dim=1, keepdim=True)
                correct += pred.eq(target.view_as(pred)).sum().item()

        accuracy = correct / length_of_dataset

        if verbose:
            print("-" * 80)
            print("Validation Accuracy: {}".format(accuracy))
        return outputs, accuracy

    def evaluate(self, teacher=False):
        """
        Evaluate method for printing accuracies of the trained network

        :param teacher (bool): True if you want accuracy of the teacher network
        """
        if teacher:
            model = deepcopy(self.teacher_model).to(self.device)
        else:
            model = deepcopy(self.student_model).to(self.device)
        _, accuracy = self._evaluate_model(model)

        return accuracy

    def get_parameters(self):
        """
        Get the number of parameters for the teacher and the student network
        """
        teacher_params = sum(p.numel() for p in self.teacher_model.parameters())
        student_params = sum(p.numel() for p in self.student_model.parameters())

        print("-" * 80)
        print("Total parameters for the teacher network are: {}".format(teacher_params))
        print("Total parameters for the student network are: {}".format(student_params))

    def post_epoch_call(self, epoch):
        """
        Any changes to be made after an epoch is completed.

        :param epoch (int) : current epoch number
        :return            : nothing (void)
        """

        pass



class Distill_IDSF:
    def __init__(self, teacher_args, student_args, teacher_module, student_module, train_dataset, val_dataset):
        super().__init__()
        self.teacher_args = teacher_args
        self.student_args = student_args
        self.teacher_module = teacher_module
        self.student_module = student_module
        self.train_dataset = train_dataset
        self.val_dataset = val_dataset

    def train_teacher(self, model_dir='./distillation/teacher.pt'):
        self.teacher_trainer = Trainer_IDSF(self.teacher_args, self.teacher_module)
        self.teacher_trainer.fit_distill(self.train_dataset, self.val_dataset)
        
    def train_student(self, model_dir='./distillation/student.pt', teacher_logits=None):
        self.student_trainer = Trainer_IDSF(self.student_args, self.student_module)
        self.student_trainer.fit_distill(self.train_dataset, self.val_dataset, teacher_logits=teacher_logits)
    def get_parameters(self):
        teacher_params = sum(p.numel() for p in self.teacher_module.model.parameters())
        student_params = sum(p.numel() for p in self.student_module.model.parameters())
        
        print("-" * 80)
        print("Total parameters for the teacher network are: {}".format(teacher_params))
        print("Total parameters for the student network are: {}".format(student_params))
        
def run_distill(teacher_args, student_args, teacher_module, student_module, train_dataset, val_dataset):
    for i in range(20):
        
        distill_module = Distill_IDSF(teacher_args, student_args, teacher_module, student_module, train_dataset, val_dataset)
        print("TEACHER HERE :))")
        teacher_logits = distill_module.train_teacher()
        print("STUDENT HERE :<<<")
        distill_module.train_student(teacher_logits=teacher_logits)
    distill_module.get_parameters()



if __name__ == "__main__":
    tokenizer = AutoTokenizer.from_pretrained("vinai/phobert-base")
    # teacher_config = AutoConfig.from_pretrained("vinai/phobert-base")
    # student_config = AutoConfig.from_pretrained("distilbert-base-uncased")
    # student_config.vocab_size = teacher_config.vocab_size
    

    # intent_label_lst, slot_label_lst = get_intent_labels(args), get_slot_labels(args)
    # teacher_model = JointPhoBERT(teacher_config, args, intent_label_lst, slot_label_lst)
    # student_model = JointDistillBERT(student_config, args, intent_label_lst, slot_label_lst)  
    # train_dataset = load_and_cache_examples(args, tokenizer, mode="train")
    # input = train_dataset[0][:3]
    # # print([i for i in train_dataset[0]])
    # # summary(model, [i.shape for i in input], batch_size=-1, dtypes=[torch.long, torch.long, torch.long, torch.long, torch.long], device='cpu')
    train_dataset = load_and_cache_examples(args, tokenizer, mode="train")
    val_dataset = load_and_cache_examples(args, tokenizer, mode="dev")

    teacher_module = IDSFModule(teacher_args)
    student_module = IDSFModule(student_args)
    student_module.config.vocab_size = teacher_module.config.vocab_size #vocab config 
    run_distill(teacher_args, student_args, teacher_module, student_module, train_dataset, val_dataset)

