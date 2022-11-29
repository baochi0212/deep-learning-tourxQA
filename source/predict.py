from trainer import *


if __name__ == '__main__':
    module = ISDFModule(args)
    test_dataset = load_and_cache_examples(args, tokenizer, mode="test")
    trainer = Trainer(args, module)
    trainer.predict(test_dataset)

