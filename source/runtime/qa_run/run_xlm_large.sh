#additional 
export freeze_weights=$1
python trainer.py --freeze $freeze_weights --pretrained --model_type xlm-roberta-large --pretrained_model xlm-roberta-large --device cuda --task QA --train_batch_size 4 --eval_batch_size 32 --learning_rate 3e-6 --logging_steps 1000 --n_epochs 15 --tuning_metric F1_score